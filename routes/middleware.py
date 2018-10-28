"""Routes WSGI Middleware"""
import re
import logging

from webob import Request

from routes.base import request_config
from routes.util import URLGenerator

log = logging.getLogger('routes.middleware')


class RoutesMiddleware(object):
    """Routing middleware that handles resolving the PATH_INFO in
    addition to optionally recognizing method overriding.

    .. Note::
        This module requires webob to be installed. To depend on it, you may
        list routes[middleware] in your ``requirements.txt``
    """
    def __init__(self, wsgi_app, mapper, use_method_override=True,
                 path_info=True, singleton=True):
        """Create a Route middleware object

        Using the use_method_override keyword will require Paste to be
        installed, and your application should use Paste's WSGIRequest
        object as it will properly handle POST issues with wsgi.input
        should Routes check it.

        If path_info is True, then should a route var contain
        path_info, the SCRIPT_NAME and PATH_INFO will be altered
        accordingly. This should be used with routes like:

        .. code-block:: python

            map.connect('blog/*path_info', controller='blog', path_info='')

        """
        #那个回调来处理
        self.app = wsgi_app
        #记录mapper对象
        self.mapper = mapper
        self.singleton = singleton
        self.use_method_override = use_method_override
        self.path_info = path_info
        self.log_debug = logging.DEBUG >= log.getEffectiveLevel()
        if self.log_debug:
            log.debug("Initialized with method overriding = %s, and path "
                      "info altering = %s", use_method_override, path_info)

    #WSGI对应的入口函数
    def __call__(self, environ, start_response):
        """Resolves the URL in PATH_INFO, and uses wsgi.routing_args
        to pass on URL resolver results."""
        old_method = None
        if self.use_method_override:
            #默认为True
            req = None

            # In some odd cases, there's no query string
            try:
                #在浏览器中访问http://localhost:8051/?age=10&hobbies=software&hobbies=tunning，可以在响应的内容中找到：
                #QUERY_STRING: age=10&hobbies=software&hobbies=tunning
                #REQUEST_METHOD: GET
                #QUERY_STRING将返回？号后的内容
                qs = environ['QUERY_STRING']
            except KeyError:
                qs = ''
            #如果QUERY_STRING中指定了‘_method',则以
            if '_method' in qs:
                req = Request(environ)
                req.errors = 'ignore'
                if '_method' in req.GET:
                    old_method = environ['REQUEST_METHOD']
                    environ['REQUEST_METHOD'] = req.GET['_method'].upper()
                    if self.log_debug:
                        log.debug("_method found in QUERY_STRING, altering "
                                  "request method to %s",
                                  environ['REQUEST_METHOD'])
            elif environ['REQUEST_METHOD'] == 'POST' and is_form_post(environ):
                if req is None:
                    req = Request(environ)
                    req.errors = 'ignore'
                if '_method' in req.POST:
                    old_method = environ['REQUEST_METHOD']
                    environ['REQUEST_METHOD'] = req.POST['_method'].upper()
                    if self.log_debug:
                        log.debug("_method found in POST data, altering "
                                  "request method to %s",
                                  environ['REQUEST_METHOD'])

        # Run the actual route matching
        # -- Assignment of environ to config triggers route matching
        if self.singleton:
            #默认为单例
            config = request_config()
            #设置mapper
            config.mapper = self.mapper
            #此句将导致，加载environ,并执行load函数，按url进行匹配,产生mapper_dic,route结果
            config.environ = environ
            match = config.mapper_dict
            route = config.route
        else:
            #直接按url进行匹配
            results = self.mapper.routematch(environ=environ)
            if results:
                match, route = results[0], results[1]
            else:
                match = route = None

        if old_method:
            environ['REQUEST_METHOD'] = old_method

        if not match:
            match = {}
            if self.log_debug:
                urlinfo = "%s %s" % (environ['REQUEST_METHOD'],
                                     environ['PATH_INFO'])
                log.debug("No route matched for %s", urlinfo)
        elif self.log_debug:
            urlinfo = "%s %s" % (environ['REQUEST_METHOD'],
                                 environ['PATH_INFO'])
            log.debug("Matched %s", urlinfo)
            log.debug("Route path: '%s', defaults: %s", route.routepath,
                      route.defaults)
            log.debug("Match dict: %s", match)

        url = URLGenerator(self.mapper, environ)
        #指明怎样的url及match被匹配
        environ['wsgiorg.routing_args'] = ((url), match)
        environ['routes.route'] = route
        environ['routes.url'] = url

        if route and route.redirect:
            route_name = '_redirect_%s' % id(route)
            location = url(route_name, **match)
            log.debug("Using redirect route, redirect to '%s' with status"
                      "code: %s", location, route.redirect_status)
            start_response(route.redirect_status,
                           [('Content-Type', 'text/plain; charset=utf8'),
                            ('Location', location)])
            return []

        # If the route included a path_info attribute and it should be used to
        # alter the environ, we'll pull it out
        if self.path_info and 'path_info' in match:
            oldpath = environ['PATH_INFO']
            newpath = match.get('path_info') or ''
            environ['PATH_INFO'] = newpath
            if not environ['PATH_INFO'].startswith('/'):
                environ['PATH_INFO'] = '/' + environ['PATH_INFO']
            environ['SCRIPT_NAME'] += re.sub(
                r'^(.*?)/' + re.escape(newpath) + '$', r'\1', oldpath)

        #调用self.app来完成具体的http请求
        response = self.app(environ, start_response)

        # Wrapped in try as in rare cases the attribute will be gone already
        try:
            del self.mapper.environ
        except AttributeError:
            pass
        return response


def is_form_post(environ):
    """Determine whether the request is a POSTed html form"""
    content_type = environ.get('CONTENT_TYPE', '').lower()
    if ';' in content_type:
        content_type = content_type.split(';', 1)[0]
    return content_type in ('application/x-www-form-urlencoded',
                            'multipart/form-data')
