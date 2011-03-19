import cherrypy
import os, os.path
import json
import sys

from re import search, compile, MULTILINE, IGNORECASE
from urlparse import urlparse, urljoin
from urllib2 import HTTPRedirectHandler, HTTPCookieProcessor, Request, build_opener
from datetime import datetime, timedelta
from BeautifulSoup import BeautifulSoup
from jinja2 import Environment, FileSystemLoader
from memcache import Client
from logging import INFO, WARNING, ERROR
from time import time

from globals import *

class Icon(object):

  def __init__(self, data=None, location=None, type=None):
    super(Icon, self).__init__()
    self.data = data
    self.location = location
    self.type = type


class TimeoutError(Exception):

  def __str__(self):
    return repr(TimeoutError)


class BaseHandler(object):

  def __init__(self):
    super(BaseHandler, self).__init__()
    self.re = compile('%([0-9a-hA-H][0-9a-hA-H])', MULTILINE)

  def htc(self, m):
    return chr(int(m.group(1), 16))

  def urldecode(self, url):
    return self.re.sub(self.htc, url)


class PrintFavicon(BaseHandler):

  def __init__(self):
    super(PrintFavicon, self).__init__()

    default_icon_data = self.open(DEFAULT_FAVICON_LOC, time()).read()
    self.default_icon = Icon(data=default_icon_data,
                             location=DEFAULT_FAVICON_LOC,
                             type=DEFAULT_FAVICON_TYPE)

    self.env = Environment(loader=FileSystemLoader(
                                    os.path.join(cherrypy.config['favicon.root'],
                                                 'templates')))

    self.mc = Client(['%(memcache.host)s:%(memcache.port)d' % cherrypy.config],
                     debug=2)

    # Initialize counters
    for counter in ['requests', 'hits', 'defaults']:
      self.mc.add('counter-%s' % counter, '0')

  def open(self, url, start, headers=None):
    time_spent = int(time() - start)
    if time_spent >= TIMEOUT:
      raise TimeoutError(time_spent)

    if not headers:
      headers = dict()
    headers.update({'User-Agent': 'Mozilla/5.0 (Windows; U; Windows NT 6.1; en-US; ' +
                                  'rv:1.9.2.13) Gecko/20101203 Firefox/3.6.13'})

    opener = build_opener(HTTPRedirectHandler(), HTTPCookieProcessor())
    return opener.open(Request(url, headers=headers),
                       timeout=min(CONNECTION_TIMEOUT, TIMEOUT - time_spent))

  def validateIconResponse(self, iconResponse):
    if iconResponse.getcode() != 200:
      cherrypy.log('Non-success response:%d fetching url:%s' % \
                   (iconResponse.getcode(), iconResponse.geturl()),
                   severity=INFO)
      return None

    iconContentType = iconResponse.info().gettype()
    if iconContentType in ICON_MIMETYPE_BLACKLIST:
      cherrypy.log('Url:%s favicon content-Type:%s blacklisted' % \
                   (iconResponse.geturl(), iconContentType),
                   severity=INFO)
      return None

    icon = iconResponse.read()
    iconLength = len(icon)

    if iconLength == 0:
      cherrypy.log('Url:%s null content length' % iconResponse.geturl(),
                   severity=INFO)
      return None

    if iconLength < MIN_ICON_LENGTH or iconLength > MAX_ICON_LENGTH:
      # Issue warning, but accept nonetheless!
      cherrypy.log('Warning: url:%s favicon size:%d out of bounds' % \
                   (iconResponse.geturl(), iconLength),
                   severity=INFO)

    return Icon(data=icon, type=iconContentType)

  # Icon at [domain]/favicon.ico?
  def iconAtRoot(self, targetDomain, start):
    cherrypy.log('Attempting to locate favicon for domain:%s at root' % \
                 targetDomain,
                 severity=INFO)

    rootIconPath = targetDomain + '/favicon.ico'

    try:
      rootDomainFaviconResult = self.open(rootIconPath, start)
      rootIcon = self.validateIconResponse(rootDomainFaviconResult)

      if rootIcon:
        cherrypy.log('Found favicon for domain:%s at root' % targetDomain,
                     severity=INFO)

        self.cacheIcon(targetDomain, rootIcon.data, rootIconPath)
        rootIcon.location = rootIconPath
        return rootIcon

    except:
      cherrypy.log('Error fetching favicon at domain root:%s, err:%s, msg:%s' % \
                   (targetDomain, sys.exc_info()[0], sys.exc_info()[1]),
                   severity=INFO)

  # Icon specified in page?
  def iconInPage(self, targetDomain, targetPath, start, refresh=True):
    cherrypy.log('Attempting to locate embedded favicon link in page:%s' % \
                 targetPath,
                 severity=INFO)

    try:
      rootDomainPageResult = self.open(targetPath, start)

      if rootDomainPageResult.getcode() == 200:
        pageSoup = BeautifulSoup(rootDomainPageResult.read())
        pageSoupIcon = pageSoup.find('link',
                                     rel=compile('^(shortcut|icon|shortcut icon)$',
                                     IGNORECASE))

        if pageSoupIcon:
          pageIconHref = pageSoupIcon.get('href')

          if pageIconHref:
            pageIconPath = urljoin(targetPath, pageIconHref)
            cherrypy.log('Found embedded favicon link:%s for domain:%s' % \
                         (pageIconPath, targetDomain),
                         severity=INFO)

            cookies = rootDomainPageResult.headers.getheaders("Set-Cookie")
            headers = None
            if cookies:
              headers = {'Cookie': ';'.join(cookies)}

            pagePathFaviconResult = self.open(pageIconPath,
                                              start,
                                              headers=headers)

            pageIcon = self.validateIconResponse(pagePathFaviconResult)
            if pageIcon:
              cherrypy.log('Found favicon at:%s for domain:%s' % \
                           (pageIconPath, targetDomain),
                           severity=INFO)

              self.cacheIcon(targetDomain, pageIcon.data, pageIconPath)
              pageIcon.location = pageIconPath
              return pageIcon

        else:
          if refresh:
            for meta in pageSoup.findAll('meta'):
              if meta.get('http-equiv', '').lower() == 'refresh':
                match = search('url=([^;]+)',
                               meta.get('content', ''),
                               flags=IGNORECASE)

                if match:
                  refreshPath = urljoin(rootDomainPageResult.geturl(),
                                        match.group(1))

                  cherrypy.log('Processing refresh directive:%s for domain:%s' % \
                               (refreshPath, targetDomain),
                               severity=INFO)

                  return self.iconInPage(targetDomain,
                                         refreshPath,
                                         start,
                                         refresh=False)

          cherrypy.log('No link tag found:%s' % targetPath, severity=INFO)

      else:
        cherrypy.log('Non-success response:%d for url:%s' % \
                     (rootDomainPageResult.getcode(), targetPath),
                     severity=INFO)

    except:
      cherrypy.log('Error extracting favicon from page:%s, err:%s, msg:%s' % \
                   (targetPath, sys.exc_info()[0], sys.exc_info()[1]),
                   severity=WARNING)

  def cacheIcon(self, domain, icon, loc):
    cherrypy.log('Caching icon at location:%s for domain:%s' % (loc, domain),
                 severity=INFO)

    if not self.mc.set('icon-%s' % domain, icon, time=MC_CACHE_TIME):
      cherrypy.log('Could not cache icon for domain:%s' % domain,
                   severity=ERROR)

  def iconInCache(self, targetDomain, start):
    icon = self.mc.get('icon-%s' % targetDomain)
    if icon:
      self.mc.incr('counter-hits')
      cherrypy.log('Cache hit:%s' % targetDomain, severity=INFO)

      cherrypy.response.headers['X-Cache'] = 'Hit'

      if icon == 'DEFAULT':
        self.mc.incr('counter-defaults')
        cherrypy.response.headers['X-Cache'] = 'Hit'
        return self.default_icon

      else:
        return Icon(data=icon)

  def writeIcon(self, icon):
    self.writeHeaders(icon)
    return icon.data

  def writeHeaders(self, icon, fmt='%a, %d %b %Y %H:%M:%S %z'):
    # MIME Type
    cherrypy.response.headers['Content-Type'] = icon.type or 'image/x-icon'

    # Set caching headers
    cherrypy.response.headers['Cache-Control'] = 'public, max-age=2592000'
    cherrypy.response.headers['Expires'] = \
                          (datetime.now() + timedelta(days=30)).strftime(fmt)

  def parse(self, url):
    # Get page path
    targetPath = self.urldecode(url)
    if not targetPath.startswith('http'):
      targetPath = 'http://%s' % targetPath
    cherrypy.log('Decoded URL:%s' % targetPath, severity=INFO)

    # Split path to get domain
    targetURL = urlparse(targetPath)
    if not targetURL or not targetURL.scheme or not targetURL.netloc:
      raise cherrypy.HTTPError(400, 'Malformed URL:%s' % url)

    targetDomain = '%s://%s' % (targetURL.scheme, targetURL.netloc)
    cherrypy.log('URL:%s, domain:%s' % (targetPath, targetDomain),
                 severity=INFO)

    return (targetPath, targetDomain)

  @cherrypy.expose
  def index(self):
    status = {'status': 'ok', 'counters': dict()}
    for counter in ['requests', 'hits', 'defaults']:
      status['counters'][counter] = self.mc.get('counter-%s' %counter)
    return json.dumps(status)

  @cherrypy.expose
  def test(self):
    topSites = open(os.path.join(cherrypy.config['favicon.root'],
                                 'topsites.txt'), 'r').read().split()
    template = self.env.get_template('test.html')
    return template.render(topSites=topSites)

  @cherrypy.expose
  def clear(self, url):
    cherrypy.log('Incoming cache invalidation request:%s' % url,
                 severity=INFO)

    targetPath, targetDomain = self.parse(str(url))
    self.mc.delete('icon_loc-%s' % targetDomain)

    cherrypy.log('Evicted cache entry for %s' % targetDomain, severity=INFO)

  @cherrypy.expose
  def s(self, url, skipCache='false'):
    start = time()

    if skipCache.lower() == 'true':
      skipCache = True
    else:
      skipCache = False

    cherrypy.log('Incoming request:%s (skipCache=%s)' % (url, skipCache),
                 severity=INFO)

    self.mc.incr('counter-requests')

    targetPath, targetDomain = self.parse(str(url))

    icon = (not skipCache and self.iconInCache(targetDomain, start)) or \
           self.iconInPage(targetDomain, targetPath, start) or \
           self.iconAtRoot(targetDomain, start)

    if not icon:
      cherrypy.log('Falling back to default icon for:%s' % targetDomain,
                   severity=INFO)

      self.cacheIcon(targetDomain, 'DEFAULT', 'DEFAULT_LOC')
      self.mc.incr('counter-defaults')
      icon = self.default_icon

    cherrypy.log('Time taken to process domain:%s %f' % \
                 (targetDomain, time() - start),
                 severity=INFO)

    return self.writeIcon(icon)


if __name__ == '__main__':
  config = os.path.join(os.getcwd(), 'dev.conf')

  cherrypy.config.update(config)
  cherrypy.config.update({'favicon.root': os.getcwd()})

  cherrypy.quickstart(PrintFavicon(), config=config)

