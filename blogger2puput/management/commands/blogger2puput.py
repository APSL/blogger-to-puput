# -*- coding: utf-8 -*-
"""Blogger to puput command module"""
import requests
import lxml.html
from pip.backwardcompat import raw_input
from optparse import make_option

try:
    from urllib.request import urlopen
except ImportError:  # Python 2
    from urllib2 import urlopen

from django.utils.text import Truncator
from django.core.files import File
from django.utils.html import strip_tags
from django.db.utils import IntegrityError
from django.utils.six.moves import input
from django.contrib.auth.models import User
from django.utils.encoding import smart_unicode
from django.contrib.sites.models import Site
from django.template.defaultfilters import slugify
from django.core.management.base import CommandError
from django.core.management.base import NoArgsCommand
from django.core.files.temp import NamedTemporaryFile

from wagtail.wagtailcore.models import Page
from wagtail.wagtailimages.models import Image as WagtailImage

from puput.models import BlogPage, EntryPage, TagEntryPage as PuputTagEntryPage, Tag as PuputTag


class Command(NoArgsCommand):
    """
    Command object for importing a Blogger blog
    into Puput via Google's gdata API.
    """
    help = 'Import a Blogger blog into Puput.'

    option_list = NoArgsCommand.option_list + (
        make_option('--blogger_title', dest='blogger_title', default='',
                    help='The tittle of blog the blogger'),
        make_option('--blogger_slug', dest='blogger_slug', default='',
                    help='The slug of blog the blogger'),
        make_option('--blogger-blog-id', dest='blogger_blog_id', default='',
                    help='The id of the Blogger blog to import'),
        make_option('--blogger_api_key', dest='blogger_api_key', default='',
                    help='The API of the Blogger blog to import'),
        make_option('--noautoexcerpt', action='store_false',
                    dest='auto_excerpt', default=True,
                    help='Do NOT generate an excerpt.'))

    SITE = Site.objects.get_current()

    def handle_noargs(self, **options):
        self.blogger_title = options.get('blogger_title')
        self.blogger_slug = options.get('blogger_slug')
        self.blogger_blog_id = options.get('blogger_blog_id')
        self.blogger_api_key = options.get('blogger_api_key')
        self.auto_excerpt = options.get('auto-excerpt', True)

        self.stdout.write('Starting migration from Blogger to Puput %s:\n')

        self.get_blog_page(options['blogger_slug'], options['blogger_title'])

        if not self.blogger_blog_id:
            self.blogger_blog_id = input('Blogger ID: ')
            if not self.blogger_blog_id:
                raise CommandError('Invalid Blogger ID')

        if not self.blogger_api_key:
            self.blogger_api_key = input('Blogger API Key: ')
            if not self.blogger_api_key:
                raise CommandError('Invalid Blogger API Key')

        self.import_authors()
        self.import_posts()

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
            self.blogpage = BlogPage(
                title=title,
                slug=slugify(title),
            )
            rootpage.add_child(instance=self.blogpage)
            revision = rootpage.save_revision()
            revision.publish()

    def import_authors(self):
        """
        Retrieve all the authors used in posts
        and convert it to new or existing author and
        return the conversion.
        """

        self.stdout.write('- Importing authors\n')

        post_authors = set()
        for post in self.get_posts():
            post_authors.add(post['author']['displayName'])

        self.stdout.write('> %i authors found.\n' % len(post_authors))

        self.authors = {}
        for post_author in post_authors:
            self.authors[post_author] = self.migrate_author(post_author.replace(' ', '-'))

    def migrate_author(self, author_name):
        """
        Handle actions for migrating the authors.
        """

        action_text = "The author '%s' needs to be migrated to an user:\n" \
                      "1. Use an existing user ?\n" \
                      "2. Create a new user ?\n" \
                      "Please select a choice: " % author_name
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
                usernames_display = ['[%s]' % username]
            else:
                usernames = []
                usernames_display = []
                preselected_user = None
                for user in users:
                    username = user.get_username()
                    if username == author_name:
                        usernames_display.append('[%s]' % username)
                        preselected_user = username
                    else:
                        usernames_display.append(username)
                    usernames.append(username)
            while True:
                user_text = "1. Select your user, by typing " \
                            "one of theses usernames:\n" \
                            "%s or 'back'\n" \
                            "Please select a choice: " % \
                            ', '.join(usernames_display)
                user_selected = raw_input(user_text)
                if user_selected in usernames:
                    break
                if user_selected == '' and preselected_user:
                    user_selected = preselected_user
                    break
                if user_selected.strip() == 'back':
                    return self.migrate_author(author_name)
            return users.get(**{users[0].USERNAME_FIELD: user_selected})
        else:
            create_text = "2. Please type the email of " \
                          "the '%s' user or 'back': " % author_name
            author_mail = raw_input(create_text)
            if author_mail.strip() == 'back':
                return self.migrate_author(author_name)
            try:
                return User.objects.create_user(author_name, author_mail)
            except IntegrityError:
                return User.objects.get(**{User.USERNAME_FIELD: author_name})

    def get_posts(self):
        res = requests.get('https://www.googleapis.com/blogger/v3/blogs/{}/posts?key={}'.format(self.blogger_blog_id,
                                                                                                self.blogger_api_key))
        if res.status_code == 200:
            return res.json()['items']

    def get_entry_tags(self, tags, entry):
        for tag in tags:
            puput_tag, created = PuputTag.objects.update_or_create(name=tag)
            entry.entry_tags.add(PuputTagEntryPage(tag=puput_tag))

    def import_posts(self):
        self.stdout.write('- Importing entries\n')

        for post in self.get_posts():
            content = post['content'] or ''
            content = self.process_content_image(content)
            excerpt = self.auto_excerpt and Truncator(
                strip_tags(smart_unicode(content))).words(50) or ''
            slug = slugify(post['title'])

            try:
                entry = EntryPage.objects.get(slug=slug)
                self.stdout.write('> Skipped %s (already migrated)\n'
                                  % entry)
            except EntryPage.DoesNotExist:
                entry = EntryPage(
                    title=post['title'],
                    body=content,
                    excerpt=excerpt,
                    slug=slugify(post['title']),
                    go_live_at=post['published'],
                    first_published_at=post['published'],
                    date=post['published'],
                    owner=User.objects.first(),
                    seo_title=post['title'],
                    search_description=excerpt,
                    live=post['published'])
                self.blogpage.add_child(instance=entry)
                revision = self.blogpage.save_revision()
                revision.publish()
                self.get_entry_tags(post.get('labels', []), entry)
                entry.save()

    def _import_image(self, image_url):
        img = NamedTemporaryFile(delete=True)
        img.write(urlopen(image_url).read())
        img.flush()
        return img

    def process_content_image(self, content):
        self.stdout.write('\tGenerate and replace entry content images....')
        if content:
            root = lxml.html.fromstring(content)
            for el in root.iter('img'):
                parent_node = next(el.iterancestors())
                if 'bp.blogspot.com' in el.attrib['src']:
                    img = self._import_image(el.attrib['src'])
                    title = el.attrib['src'].rsplit('/', 1)[1]
                    new_image = WagtailImage(file=File(file=img, name=title), title=title)
                    new_image.save()
                    el.attrib['src'] = new_image.get_rendition('original').file.url
                    parent_node.attrib['href'] = new_image.get_rendition('original').file.url
                    self.stdout.write('\t\t{}'.format(el.attrib['src']))
            content = lxml.html.tostring(root, pretty_print=True)
        return content
