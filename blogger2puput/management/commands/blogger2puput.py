# -*- coding: utf-8 -*-
"""Blogger to puput command module"""
import requests
import lxml.html
import lxml.etree as ET
from optparse import make_option

from django.contrib.auth import get_user_model
from six.moves import input

from django.utils.text import Truncator
from django.core.files import File
from django.utils.html import strip_tags
from django.db.utils import IntegrityError
from django.contrib.sites.models import Site
from django.template.defaultfilters import slugify
from django.core.management.base import NoArgsCommand
from django.core.files.temp import NamedTemporaryFile

from wagtail.wagtailcore.models import Page
from wagtail.wagtailimages.models import Image as WagtailImage
from puput.models import BlogPage, EntryPage, TagEntryPage as PuputTagEntryPage, Tag as PuputTag


BLOGGER_URL = 'https://www.googleapis.com/blogger/v3/blogs/{}/posts/?maxResults=500&key={}'


class Command(NoArgsCommand):
    help = 'Import blog data from Blogger.'

    option_list = NoArgsCommand.option_list + (
        make_option('--slug', default='blog', help="Slug of the blog."),
        make_option('--title', default='Blog', help="Title of the blog."),
        make_option('--blogger_blog_id', dest='blogger_blog_id', default='', help='Id of the Blogger blog to import.'),
        make_option('--blogger_api_key', dest='blogger_api_key', default='',
                    help='API Key of the Blogger blog to import.')
    )

    SITE = Site.objects.get_current()

    def handle_noargs(self, **options):
        self.blogger_blog_id = options.get('blogger_blog_id')
        self.blogger_api_key = options.get('blogger_api_key')
        self.get_blog_page(options['slug'], options['title'])
        self.blogger_entries = self.get_blogger_entries()
        self.import_authors()
        self.import_entries()

    def get_blog_page(self, slug, title):
        # Create blog page
        try:
            self.blogpage = BlogPage.objects.get(slug=slug)
        except BlogPage.DoesNotExist:
            # Get root page
            rootpage = Page.objects.first()

            # Set site root page as root site page
            site = Site.objects.first()
            site.root_page = rootpage
            site.save()

            # Get blogpage content type
            self.blogpage = BlogPage(title=title, slug=slug)
            rootpage.add_child(instance=self.blogpage)
            revision = rootpage.save_revision()
            revision.publish()

    def import_authors(self):
        self.stdout.write('Importing authors...')

        entry_authors = set()
        for entry in self.blogger_entries:
            entry_authors.add(entry['author']['displayName'])

        self.stdout.write(u'{0:d} authors found.'.format(len(entry_authors)))
        self.authors = {}
        for entry_author in entry_authors:
            self.authors[entry_author] = self.import_author(entry_author.replace(' ', '-'))

    def import_author(self, author_name):
        action_text = u"The author '{0:s}' needs to be migrated to an user:\n" \
                      u"1. Use an existing user ?\n" \
                      u"2. Create a new user ?\n" \
                      u"Please select a choice: ".format(author_name)
        User = get_user_model()
        while True:
            selection = str(input(action_text))
            if selection and selection in '12':
                break
        if selection == '1':
            users = User.objects.all()
            if users.count() == 1:
                username = users[0].get_username()
                preselected_user = username
                usernames = [username]
                usernames_display = [u'[{0:s}]'.format(username)]
            else:
                usernames = []
                usernames_display = []
                preselected_user = None
                for user in users:
                    username = user.get_username()
                    if username == author_name:
                        usernames_display.append(u'[{0:s}]'.format(username))
                        preselected_user = username
                    else:
                        usernames_display.append(username)
                    usernames.append(username)
            while True:
                user_text = u"1. Select your user, by typing " \
                            u"one of theses usernames:\n" \
                            u"{0:s} or 'back'\n" \
                            u"Please select a choice: ".format(', '.join(usernames_display))
                user_selected = input(user_text)
                if user_selected in usernames:
                    break
                if user_selected == '' and preselected_user:
                    user_selected = preselected_user
                    break
                if user_selected.strip() == 'back':
                    return self.import_author(author_name)
            return users.get(**{users[0].USERNAME_FIELD: user_selected})
        else:
            create_text = u"2. Please type the email of " \
                          u"the '{0:s}' user or 'back': ".format(author_name)
            author_mail = input(create_text)
            if author_mail.strip() == 'back':
                return self.import_author(author_name)
            try:
                return User.objects.create_user(author_name, author_mail)
            except IntegrityError:
                return User.objects.get(**{User.USERNAME_FIELD: author_name})

    def get_blogger_entries(self):
        res = requests.get(BLOGGER_URL.format(self.blogger_blog_id, self.blogger_api_key))
        if res.status_code == 200:
            return res.json()['items']

    def import_entry_tags(self, tags, entry):
        for tag in tags:
            puput_tag, created = PuputTag.objects.update_or_create(name=tag)
            entry.entry_tags.add(PuputTagEntryPage(tag=puput_tag))

    def import_entries(self):
        self.stdout.write('Importing entries...')

        for entry in self.blogger_entries:
            content = entry['content'] or ''
            content = self.process_content_image(content)
            excerpt = Truncator(content).words(50) or ''
            slug = slugify(entry['title'])
            try:
                page = EntryPage.objects.get(slug=slug)
            except EntryPage.DoesNotExist:
                entry_author = entry['author']['displayName'].replace(' ', '-')
                page = EntryPage(
                    title=entry['title'],
                    body=content,
                    excerpt=strip_tags(excerpt),
                    slug=slugify(entry['title']),
                    go_live_at=entry['published'],
                    first_published_at=entry['published'],
                    date=entry['published'],
                    owner=self.authors[entry_author],
                    seo_title=entry['title'],
                    search_description=excerpt,
                    live=entry['published'])
                self.blogpage.add_child(instance=page)
                revision = self.blogpage.save_revision()
                revision.publish()
            self.import_entry_tags(entry.get('labels', []), page)
            page.save()

    def _import_image(self, image_url):
        image = NamedTemporaryFile(delete=True)
        response = requests.get(image_url)
        if response.status_code == 200:
            image.write(response.content)
            image.flush()
            return image
        return

    def _image_to_embed(self, image):
        return u'<embed alt="{}" embedtype="image" format="fullwidth" id="{}"/>'.format(image.title, image.id)

    def process_content_image(self, content):
        self.stdout.write('\tGenerate and replace entry content images....')
        if content:
            root = lxml.html.fromstring(content)
            for img_node in root.iter('img'):
                parent_node = img_node.getparent()
                if 'bp.blogspot.com' in img_node.attrib['src']:
                    self.stdout.write('\t\t{}'.format(img_node.attrib['src']))
                    image = self._import_image(img_node.attrib['src'])
                    if image:
                        title = img_node.attrib['src'].rsplit('/', 1)[1]
                        new_image = WagtailImage(file=File(file=image), title=title)
                        new_image.save()
                        if parent_node.tag == 'a':
                            parent_node.addnext(ET.XML(self._image_to_embed(new_image)))
                            parent_node.drop_tree()
                        else:
                            parent_node.append(ET.XML(self._image_to_embed(new_image)))
                            img_node.drop_tag()
            content = ET.tostring(root)
        return content
