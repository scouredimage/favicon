import sys
import site

sys.stdout = sys.stderr

ROOT='/opt/favicon_env'

prev_sys_path = list(sys.path)

# Add site-packages of our virtualenv as a site directory
site.addsitedir(ROOT + '/venv/lib/python2.6/site-packages/')
# Add application directory to PYTHONPATH
sys.path.append(ROOT + '/src')

# Reorder sys.path so added directories take precedence
new_sys_path = [p for p in sys.path if p not in prev_sys_path]
for item in new_sys_path:
  sys.path.remove(item)
sys.path[:0] = new_sys_path

import cherrypy
import atexit
from logging import handlers, INFO

# Remove the default FileHandlers if present.
cherrypy.log.error_file = ''

# Make a new RotatingFileHandler for the error log.
err_fname = getattr(cherrypy.log,
                    'rot_error_file',
                    ROOT + '/logs/errorLog')

err_handler = handlers.TimedRotatingFileHandler(err_fname, 'midnight', 1, 7)
err_handler.setLevel(INFO)
err_handler.setFormatter(cherrypy._cplogging.logfmt)

cherrypy.log.error_log.addHandler(err_handler)

# Load config
config = ROOT + '/src/prod.conf'
cherrypy.config.update(config)
cherrypy.config.update({'favicon.root' : ROOT + '/src'})

if cherrypy.__version__.startswith('3.0') and cherrypy.engine.state == 0:
  cherrypy.engine.start(blocking=False)
  atexit.register(cherrypy.engine.stop)

import favicon

application = cherrypy.Application(favicon.PrintFavicon(),
                                   script_name=None,
                                   config=config)
