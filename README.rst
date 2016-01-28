blogger-to-puput
================

Import your Blogger blog data into Puput.

Usage
-----
1. Install blogger2puput package and its dependencies :code:`pip install blogger2puput`
2. Add :code:`blogger2puput` to your :code:`INSTALLED_APPS` in :code:`settings.py` file.
3. Run the management command::

    python manage.py blogger2puput --blogger_blog_id=Your BlogID --blogger_api_key=Your APIKey

You can optionally pass the slug and the title of the blog to the importer::

    python manage.py blogger2puput --slug=blog --title="Puput blog" --blogger_blog_id=Your BlogID --blogger_api_key=Your APIKey


