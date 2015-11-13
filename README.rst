zinnia-to-puput
===============

Import your Zinnia blog data into Puput.

Usage
-----
1. Install zinnia-to-puput package and its dependencies :code:`pip install zinnia-to-puput`
2. Add :code:`zinnia2puput` to your :code:`INSTALLED_APPS` in :code:`settings.py` file.
3. Run the management command::

    python manage.py zinnia2import

You can optionally pass the slug and the title of the blog to the importer::

    python manage.py zinnia2import --slug=blog --title="Puput blog"


