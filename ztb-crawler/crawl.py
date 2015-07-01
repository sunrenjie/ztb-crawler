#!/usr/bin/python
# -*- coding: utf-8 -*-

import os
import sys
import re
import time
import datetime
import hashlib
from urlparse import urljoin
import requests
import bs4


class HTMLTagAttributesVerifier(object):
    def __init__(self, tag, attributes, attributes_blacklist = None):
        """

        :param tag: HTML tag name
        :param attributes: dict of attribute-name, attribute-value
        :param attributes_blacklist: iterable of the names of the attributes
                                     that are not expected to exist in the tag
        :return:
        """
        self.tag = tag
        assert isinstance(attributes, dict)
        self.attributes = attributes
        self.attributes_blacklist = attributes_blacklist

    def verify1(self, tag, attributes):
        """
        :param attributes: a list of tuples just as the 'attrs' parameter for
                           HTMLParser.handle_starttag()
        """
        if tag != self.tag:
            return False
        accumulated = set()
        for attr in attributes:
            k, v = attr
            if k in self.attributes:
                if self.attributes[k] == v:
                    accumulated.add(k)
                else:
                     return False
            if self.attributes_blacklist and k in self.attributes_blacklist:
                return False
        return True if len(accumulated) == len(self.attributes) else False

    def verify2(self, soup_tag):
        """

        :param soup_tag: a tag of type bs4.element.Tag (as used by
                        BeautifulSoup to represent HTML tag)
        :return:
        """
        if soup_tag.name != self.tag:
            return False
        for k, v in self.attributes.iteritems():
            r = soup_tag.get(k)
            # TODO: consider improvements.
            # The get() return a list for 'class' attribute, string for others.
            if isinstance(r, list):
                r = ' '.join(sorted(r))
            if r != v:
                return False
        if self.attributes_blacklist:
            for k, v in self.attributes_blacklist.iteritems():
                if soup_tag.get(k) == v:
                    return False
        return True


class CrawlerDataSource(object):

    __location_selector__ = None

    @classmethod
    def register_location_prefixes(cls, prefixes, c):
        if not cls.__location_selector__:
            cls.__location_selector__ = {}
        for prefix in prefixes:
            cls.__location_selector__[prefix] = c

    @classmethod
    def fetch_text_impl(cls, location):
        pass

    @classmethod
    def fetch_and_yield_lines_impl(cls, location):
        pass

    @staticmethod
    def prefixes():
        pass

    @classmethod
    def subclass_selector(cls, location):
        if not cls.__location_selector__:
            for c in cls.__subclasses__():
                cls.register_location_prefixes(c.prefixes(), c)
        assert cls.__location_selector__
        for pattern, c in cls.__location_selector__.iteritems():
            if re.search(pattern, location):
                return c
        raise LookupError("handler for location %s not implemented" % location)

    @classmethod
    def fetch_text(cls, location):
        c = cls.subclass_selector(location)
        return c.fetch_text_impl(location)

    @classmethod
    def fetch_and_yield_lines(cls, location):
        c = cls.subclass_selector(location)
        return c.fetch_and_yield_lines_impl(location)

    @staticmethod
    def decode_string_with_unknown_encoding(s):
        decoded = False
        # TODO: list all encodings that occur in practice here for us to try
        for encoding in ['utf-8', 'gbk']:
            try:
                s = s.decode(encoding)
                decoded = True
                break
            except UnicodeDecodeError:
                pass
        if decoded:
                return s
        else:
            raise UnicodeError("impossible: cannot decode input string")


class CrawlerDataSourceWebPage(CrawlerDataSource):
    @staticmethod
    def __split_text_and_yield_lines__(text):
        assert text.index('html')
        for l in text.split('\n'):
            yield l.rstrip('\r')

    @classmethod
    def fetch_text_impl(cls, location):
        retrying = 3
        status_code = None
        headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/42.0.2311.152 Safari/537.36',  # exactly that of my dev browser
        }
        while retrying:
            try:
                r = requests.get(location, headers=headers)
                if r.status_code == 200:  # request OK.
                    return cls.decode_string_with_unknown_encoding(r.content)
                else:
                    status_code = r.status_code
            except:
                pass
            time.sleep(5)  # TODO: elaborate on this
            retrying -= 1
        status_code = str(status_code) if status_code else '<unknown>'
        raise IOError("Request for the url '%s' returns status code %s" % (location, status_code))

    @classmethod
    def fetch_and_yield_lines_impl(cls, location):
        return cls.__split_text_and_yield_lines__(cls.fetch_text_impl(location))

    @staticmethod
    def prefixes():
        return [r'^http://', r'^https://']


class CrawlerDataSourceLocalFile(CrawlerDataSource):

    @staticmethod
    def get_local_file_path_from_url(location):
        return re.sub(r'file:///', r'/', location)

    @classmethod
    def fetch_text_impl(cls, location):
        with open(cls.get_local_file_path_from_url(location), "r") as h:
            return cls.decode_string_with_unknown_encoding(h.read())

    @classmethod
    def fetch_and_yield_lines_impl(cls, location):
        with open(cls.get_local_file_path_from_url(location), "r") as h:
            for l in h:
                yield cls.decode_string_with_unknown_encoding(l.strip())

    @staticmethod
    def prefixes():
        return [r'^/', r'./', r'^file:///']  # TODO: not compatible with DOS/Windows


class SoupAncestorSearch(object):
    def __init__(self, path, verifier):
        """
        :param path: iterable of tag names from this tag (exclusive) up to this
                     ancestor (inclusive); if it is empty, then we are
                     actually verifying this tag proper
        :param verifier: HTMLTagAttributesVerifier object
        """
        self.path = path
        self.verifier = verifier
    
    def is_the_soup_tag_has_it(self, tag):
        t = tag
        for p in self.path:
            if not t.parent or t.parent.name != p:
                return False
            t = t.parent
        return self.verifier.verify2(t)

    @staticmethod
    def search_soup_for_tags(soup, name, searches):
        for t in soup.find_all(name):
            matched = True
            for s in searches:
                if not s.is_the_soup_tag_has_it(t):
                    matched = False
                    break
            if matched:
                yield t


class ZTBParser(object):
    @staticmethod
    def parse_article_time_from_td(s):
        #  The in-td time string is of the format 'YYYY-mm-dd', or 'mm-dd'
        #  and may optionally be enclosed in '[]'.
        s = re.sub('[\[\]]', '', s)  # remove enclosing '[]' if necessary
        try:
            t = datetime.datetime.strptime(s, '%Y-%m-%d')
            if t:
                return t.strftime('%Y-%m-%d')
        except ValueError:  # data-format mismatch
            pass
        try:
            t = datetime.datetime.strptime(s, '%m-%d')
            if t:
                return t.strftime('%m-%d')
        except ValueError:  # data-format mismatch
            pass
        return None

    @staticmethod
    def walk_down_tag_with_single_edge(tag):
        t = tag
        while True:
            children = [e for e in t.children]
            if len(children) != 1:
                return None
            t = children[0]
            if not isinstance(t, bs4.element.Tag):
                return t.strip()

    @classmethod
    def parse_article_time_from_anchor(cls, a):
        for tag in a.parent.parent.children:
            if tag.name != u'td':
                continue
            t = cls.walk_down_tag_with_single_edge(tag)
            if t:
                ti = cls.parse_article_time_from_td(t)
                if ti:
                    return ti
        return None

    @staticmethod
    def get_context_path(s):  # will always return with terminal '/'
        b = s.index('//')
        assert b > 0
        c = s.index('/', b + 2)
        if c > 0:
            return s[0 : c + 1]
        else:
            return s + '/'

    @staticmethod
    def get_path_one_level_up(s):  # will always return with terminal '/'
        b = s.index('//')
        assert b > 0
        c = s.rfind('/')
        assert s[c - 1] != '/'  # shall not be part of '//' of the protocol field
        return s[0: c + 1]

    @classmethod
    def generator_yxztb(cls, flow, soup_tag):
        """

        :param flow:
        :param soup_tag: the anchor containing our record
        :return:
        """
        addr = soup_tag.get('href')
        t = cls.parse_article_time_from_anchor(soup_tag)
        assert t is not None
        title = cls.walk_down_tag_with_single_edge(soup_tag)
        assert title is not None
        if addr[0:4] != 'http':  # not full address; compute it
            addr = urljoin(flow.url, addr)
        # TODO: ugly hacking; improve it
        # time from 'ztb.huzhou.gov.cn' is of 'mm-dd'; fortunately, urls are
        # like http://ztb.huzhou.gov.cn/art/2015/6/15/art_3604_398438.html
        if len(t) != 10:
            # construct a full date with the help of url
            segments = addr.split('/')
            segments = [ '0' + i if len(i) == 1 else i for i in segments]
            for i in xrange(0, len(segments) - 1):
                if ('%s-%s' % (segments[i], segments[i+1])) == t:
                    t = datetime.datetime.strptime(
                        '-'.join(segments[i-1 : i+2]), '%Y-%m-%d').strftime(
                        '%Y-%m-%d')
        assert len(t) == 10
        return [
            flow.name, t, addr, title, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ]


class ZTBCrawlFlow(object):
    def __init__(self, url, location, name, tag, searches, generator):
        """

        :param url: target web page url
        :param location: the actual location to read the data from; when it
                         is defined and differs from url; then the data at
                         location must be a cached version of url
        :param name: descriptive name given to the web page
        :param tag: name of the tag around which the crawl is centered
        :param searches: list of SoupAncestorSearch objects that help identify
                         the tag
        :param generator: generator that emit the records collected
        :return:
        """
        self.url = url
        self.location = location
        self.name = name
        self.tag = tag
        self.searches = searches
        self.generator = generator

def get_crawl_workflows():
    crawl_flows={}
    for f in [
        ZTBCrawlFlow('http://www.yxztb.net/yxweb/zypd/012001/012001001/', './sample-data/yi-xin', u'宜兴市', 'a',
                     [
                         SoupAncestorSearch(['td'], HTMLTagAttributesVerifier(
                             'td', {'class': 'tdmoreinfosub'})),
                         SoupAncestorSearch(['td', 'tr', 'table'], HTMLTagAttributesVerifier(
                             'table', {'class': 'tbmoreinfosub'}))
                     ], ZTBParser.generator_yxztb),
        ZTBCrawlFlow('http://www.wxzb.net/wxzb/ZtbInfo/MoreZBGG.aspx', './sample-data/wu-xi', u'无锡市', 'a',
                     [
                         SoupAncestorSearch(['td', 'tr', 'table'], HTMLTagAttributesVerifier(
                             'table', {'id': 'DataGrid1'})),
                         SoupAncestorSearch(['td', 'tr', 'table', 'td'], HTMLTagAttributesVerifier(
                             'td', {'id': 'tdcontent'})),
                         SoupAncestorSearch(['td', 'tr', 'table', 'td', 'tr', 'table'],
                                            HTMLTagAttributesVerifier('table', {'id': 'moreinfo'})),
                     ], ZTBParser.generator_yxztb),
        ZTBCrawlFlow('http://www.ggzy.com.cn/jyweb/ShowInfo/Moreinfo.aspx?CategoryNum=003001001001',
                     './sample-data/jiang-yin', u'江阴市', 'a',
                     [
                         SoupAncestorSearch(['td', 'tr', 'table'], HTMLTagAttributesVerifier(
                             'table', {'id': 'MoreInfoList1_DataGrid1'})),
                         SoupAncestorSearch(['td', 'tr', 'table', 'td'], HTMLTagAttributesVerifier(
                             'td', {'id': 'MoreInfoList1_tdcontent'})),
                         SoupAncestorSearch(['td', 'tr', 'table', 'td', 'tr', 'table'],
                                            HTMLTagAttributesVerifier('table', {'id': 'MoreInfoList1_moreinfo'})),
                     ], ZTBParser.generator_yxztb),
        ZTBCrawlFlow('http://zhaotoubiao.sipac.gov.cn/yqztbweb/ShowInfo/MoreInfo_zbgg.aspx?categoryNum=001001',
                     './sample-data/su-zhou', u'苏州工业园区', 'a',
                     [
                         SoupAncestorSearch(['td', 'tr', 'table'], HTMLTagAttributesVerifier(
                             'table', {'id': 'DataGrid1'})),
                     ], ZTBParser.generator_yxztb),
        ZTBCrawlFlow('http://www.haztb.gov.cn/hawz/jyxx/004001/004001001/',
                     './sample-data/huai-an', u'淮安市', 'a',
                     [
                         SoupAncestorSearch(['td', 'tr'], HTMLTagAttributesVerifier(
                             'tr', {'height': '22'}
                         )),
                         SoupAncestorSearch(['td', 'tr', 'table'], HTMLTagAttributesVerifier(
                             'table', {'width': '99%'})),
                     ], ZTBParser.generator_yxztb),
        ZTBCrawlFlow('http://www.cxztb.gov.cn:8080/cxxztb/jyxx/003001/003001001/003001001001/MoreInfo.aspx?CategoryNum=003001001001',
                     './sample-data/chang-xin', u'长兴县', 'a',
                     [
                         SoupAncestorSearch(['td', 'tr', 'table'], HTMLTagAttributesVerifier(
                             'table', {'id': 'MoreInfoList1_DataGrid1'})),
                     ], ZTBParser.generator_yxztb),
        ZTBCrawlFlow('http://ztb.huzhou.gov.cn/col/col3604/index.html', './sample-data/hu-zhou', u'湖州市', 'a',
                     [
                         SoupAncestorSearch(['td', 'tr', 'table', 'div', 'div'], HTMLTagAttributesVerifier(
                             'div', {'id': '5824'})),
                     ], ZTBParser.generator_yxztb),
        ZTBCrawlFlow('http://www.czzbb.net/czztb/jyxx/010001/010001001/',
                     './sample-data/chang-zhou', u'常州市', 'a',
                     [
                         SoupAncestorSearch(['td', 'tr'], HTMLTagAttributesVerifier(
                             'tr', {'height': '22'}
                         )),
                         SoupAncestorSearch(['td', 'tr', 'table'], HTMLTagAttributesVerifier(
                             'table', {'width': '99%'})),
                     ], ZTBParser.generator_yxztb),
        ZTBCrawlFlow('http://ggzy.njzwfw.gov.cn/njggzy/jsgc/001001/001001001/001001001002/',
                     './sample-data/nan-jing', u'南京市', 'a',
                     [
                         SoupAncestorSearch(['td', 'tr', 'table', 'div', 'td', 'tr', 'table'],
                                            HTMLTagAttributesVerifier(
                                                'table', {'width': '998', 'class': 'bk'})),
                     ], ZTBParser.generator_yxztb),
    ]:
        crawl_flows[f.url] = f
    return crawl_flows


def log_it(s, handle):
    handle.write(s + '\n')
    print s


def commit(flow, data, prefix, log):
    # data: [flow.name, t, addr, title, collected-time-point]
    (name, t, addr, title, _) = data
    t1 = t[0:7]  # 'YYYY-mm'
    t2 = t[8:]   # 'dd
    path = '/'.join([prefix, name, t1, t2])
    if not os.access(path, os.R_OK):
        os.makedirs(path)
    assert os.access(path, os.R_OK)
    digest = hashlib.md5(addr).hexdigest()
    f = path + '/' + digest
    if not os.access(f, os.W_OK):
        with open(log, 'a') as lh:
            log_it('#Info: created new data entry in file "%s"' % f, lh)
            log_it('         %s' % '\t'.join(data), lh)
            with open(f, 'w') as h:
                h.write('\t'.join(data) + '\n')


def main():
    if len(sys.argv) != 2:
        print "Usage: %s prefix-directory" % sys.argv[0]
        exit()
    prefix = sys.argv[1]
    log = '%s/ztb-crawler-%s.log' % (prefix, datetime.datetime.now().strftime("%Y%m%d%H%M%S"))
    print '#Info: log will be written to "%s"' % os.path.abspath(log)
    for url, flow in get_crawl_workflows().iteritems():
        try:
            text = CrawlerDataSource.fetch_text(flow.location if flow.location else flow.url)
            soup = bs4.BeautifulSoup(text, 'html.parser')
            for a in SoupAncestorSearch.search_soup_for_tags(soup, flow.tag, flow.searches):
                data = flow.generator(flow, a)
                commit(flow, data, prefix, log)
            print '#Info: job for url "%s" succeeded' % url
        except:
            print '#Error: job for url "%s" failed' % (url)
    print '#Info: log has been written to "%s"' % os.path.abspath(log)


main()
