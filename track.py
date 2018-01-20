# coding: utf-8

# region >>>>>>>>>>> sampling >>>>>>>>>>
"""
总流程：
    1. 对每一个用户请求其follower数
    2. 存储到数据库（原）中。
    3. 根据follower数排序。
    4. 使用分层抽样的方法抽取1000个用户.

    1. 一共17473个用户，从数据库中把用户的id全部取出，加载到内存。
    2. 30个为一组，pool参数设置为20;
    3. 判断id是否有效->请求用户页面。
    4. 判断页面是否请求成功->解析页面数据。
    5. 判断页面解析是否成功->更新数据库
    6. 取出所有的用户数据，根据follower数进行排序分层
    7. 使用分层抽样的方法抽取1000个用户。
    8. 将新抽取的用户存入新的数据中。
"""
# endregion <<<<<<<<<<< sampling <<<<<<<<<<

import requests
import json
from config import logger, XConfig
from multiprocessing import Pool
from database import SqlXigua
from xigua import VideoPage
from tempor import Tempor
from datetime import datetime
import time
import sqlite3
from apscheduler.schedulers.blocking import BlockingScheduler
from utilities import record_data
import sys

db = SqlXigua()


class Instance:
    """
    抽取17000个用于跟踪的用户：真的要这么多吗？
    """
    all_user = [user[0] for user in db.get_all_users()]

    def __init__(self):
        self._base_user_url = 'https://m.ixigua.com/video/app/user/home/'
        self.new_videos = []
        self._pool_size = 70
        self.headers = XConfig.HEADERS_1
        self.proxies = None

        # 已经把第一次的记录放进去了
        self.get_new_videos()

    def get_users_url(self, user_ids):
        """
        从user_id中提取用户页面的url
        :param user_ids: 用户id
        :return:
        """
        if not isinstance(user_ids, (list, tuple)):
            logger.error('user_ids must be list or tuple in func=get_user_url')
        user_urls = []
        pre_params = {
            'to_user_id': '',
            'format': 'json'
        }
        for user_id in user_ids:
            pre_params['to_user_id'] = user_id
            user_urls.append(Instance._url_join(self._base_user_url, pre_params))
        return user_urls

    def get_user_url(self, user_id):
        """
        :return:
        """
        params = {
            'to_user_id': user_id,
            'format': 'json'
        }
        return Instance._url_join(self._base_user_url, params)

    @staticmethod
    def _url_join(base_url, params):
        """
        连接url和params
        :param base_url:
        :param params:
        :return:
        """
        if not isinstance(params, dict):
            logger.error('url params must be dictionary')

        if base_url[-1] != '?':
            base_url += '?'
        for keys in params:
            item = "{}={}&".format(keys, params[keys])
            base_url += item
        return base_url[:-1]

    def get_new_videos(self):
        for i in range(int(len(self.all_user) / self._pool_size)):
            with Pool(self._pool_size) as p:
                video_id_ss = p.map(self._get_new_video,
                                    self.all_user[i * self._pool_size: (i + 1) * self._pool_size])
            for video_ids in video_id_ss:
                self.new_videos.extend(video_ids)

        for video_id in self.new_videos:
            t = Tempor(video_id, datetime.now(),
                       views=0, likes=0, dislikes=0,
                       comments=0)
            try:
                db.insert(t, is_commit=False)
            except sqlite3.InterfaceError:
                print(video_id)
        db.conn.commit()

    def switch_headers(self):
        if len(self.headers['user-agent']) == len(XConfig.HEADERS_1['user-agent']):
            self.headers = XConfig.HEADERS_2
        else:
            self.headers = XConfig.HEADERS_1

    @staticmethod
    def get_proxy(count=1):
        base_url = 'http://www.mogumiao.com/proxy/api/get_ip_al'
        params = {
            'appKey': '7f52750cc46548b7b316bfaf73792f70',
            'count': count,
            'expiryDate': 5,
            'format': 1
        }
        res = {}
        try:
            r = requests.get(base_url, params)
            if r.status_code != 200:
                logger.error('cannot get proxy from {}'.format(base_url))
                return res
            data = json.loads(r.text)
            if data['code'] != '0':
                logger.error('{} server error'.format(base_url))
                return res
            proxy = 'http://{}:{}'.format(data['msg'][0]['ip'], data['msg'][0]['port'])
            res['http'] = proxy
            res['https'] = proxy
            return res
        except (requests.HTTPError, requests.ConnectionError,
                requests.Timeout, json.JSONDecodeError):
            return {}
        except KeyError:
            return res

    @staticmethod
    def is_valid_proxy(proxy, timeout=2):
        """
        :param proxy:
        :param timeout:
        :return:
        """
        xigua_headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'accept-encoding': 'gzip, deflate, br',
            'accept-language': 'en-US,en;q=0.9,pt;q=0.8,zh-CN;q=0.7,zh;q=0.6',
            'cache-control': 'max-age=0',
            'referer': 'https',
            'upgrade-insecure-requests': '1',
            'user-agent': 'Mozilla/5.0 (Linux; Android 5.0; SM-G900P Build/LRX21T) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.132 Mobile Safari/537.36',
        }

        xigua_url = 'http://m.365yg.com/video/app/user/home/'
        xigua_params = {
            'to_user_id': '6597794261',
            'device_id': '42136171291',
            'format': 'json',
            'app': 'video_article',
            'utm_source': 'copy_link',
            'utm_medium': 'android',
            'utm_campaign': 'client_share',
        }
        try:
            requests.get(url=xigua_url,
                         params=xigua_params,
                         headers=xigua_headers,
                         proxies=proxy,
                         timeout=timeout)
            return True
        except requests.exceptions.ProxyError:
            return False
        except requests.Timeout:
            return False

    @staticmethod
    def test_no_proxy(timeout=2):
        xigua_headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'accept-encoding': 'gzip, deflate, br',
            'accept-language': 'en-US,en;q=0.9,pt;q=0.8,zh-CN;q=0.7,zh;q=0.6',
            'cache-control': 'max-age=0',
            'referer': 'https',
            'upgrade-insecure-requests': '1',
            'user-agent': 'Mozilla/5.0 (Linux; Android 5.0; SM-G900P Build/LRX21T) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/63.0.3239.132 Mobile Safari/537.36',
        }
        xigua_url = 'http://m.365yg.com/video/app/user/home/'
        xigua_params = {
            'to_user_id': '6597794261',
            'device_id': '42136171291',
            'format': 'json',
            'app': 'video_article',
            'utm_source': 'copy_link',
            'utm_medium': 'android',
            'utm_campaign': 'client_share',
        }
        try:
            req = requests.get(url=xigua_url,
                               params=xigua_params,
                               headers=xigua_headers,
                               timeout=timeout)
            if req.status_code != 403:
                return True
            else:
                return False
        except requests.Timeout:
            return False

    @staticmethod
    def update_proxy():
        for i in range(20):
            if Instance.test_no_proxy():
                # 经过测试，没有代理是可以正常访问的
                return None  # 设置没有代理的模式

            proxy = Instance.get_proxy()
            if Instance.is_valid_proxy(proxy):
                # 测试代理是否有效，如果有效的话返回该代理。
                return proxy
        # 20个代理都没用就gg了
        return None

    def occur_403(self, times=0):
        """
        错误
        :param times:连续请求的第几次出现403错误
        :return:
        """
        if times == 1:
            self.switch_headers()  # 换一个头部心事看看能不能用
            return True
        elif times == 2:
            self.proxies = Instance.update_proxy()
            if self.proxies is None:
                return False
            else:
                return True
        elif times == 3:
            return False

    def _get_new_video(self, user_id):
        """
        解析用户页面
        :param user_id:
        :return: User对象
        """
        # headers = XConfig.HEADERS_1

        base_user_url = 'http://m.365yg.com/video/app/user/home/'
        params = {
            'to_user_id': user_id,
            'device_id': '42136171291',
            'format': 'json',
            'app': 'video_article',
            'utm_source': 'copy_link',
            'utm_medium': 'android',
            'utm_campaign': 'client_share',
        }
        video_ids = []
        try:
            if self.proxies is None:
                req = requests.get(base_user_url,
                                   params=params,
                                   headers=self.headers,
                                   timeout=XConfig.TIMEOUT)
                if req.status_code == 403:
                    self.occur_403(1)
                    req = requests.get(base_user_url,
                                       params=params,
                                       headers=self.headers,
                                       timeout=XConfig.TIMEOUT)
                    if req.status_code == 403:
                        self.occur_403(2)
                        req = requests.get(base_user_url,
                                           params=params,
                                           headers=self.headers,
                                           proxies=self.proxies,
                                           timeout=XConfig.TIMEOUT)
            else:
                req = requests.get(base_user_url,
                                   params=params,
                                   proxies=self.proxies,
                                   headers=self.headers,
                                   timeout=XConfig.TIMEOUT)
                if req.status_code == 403:
                    self.occur_403(1)  # 更新头部信息。
                    req = requests.get(base_user_url,
                                       params=params,
                                       headers=self.headers,
                                       proxies=self.proxies,
                                       timeout=XConfig.TIMEOUT)
                    if req.status_code == 403:
                        self.occur_403(2)  # 会更新代理。
                        req = requests.get(base_user_url,
                                           params=params,
                                           headers=self.headers,
                                           proxies=self.proxies,
                                           timeout=XConfig.TIMEOUT)

            if req.status_code == 403:
                logger.error('forbidden by ixigua.com!!!')
                return []

            data = json.loads(req.text.encode('utf-8'), encoding='ascii')
            if data['message'] != 'success':
                logger.info('do not success when request user page!')

            now = time.time()
            for item_v in data['data']:
                try:
                    # 五分钟以内上传的视频都可以算作新视频
                    if now - int(item_v['publish_time']) < 360:
                        video_id = item_v['group_id_str']
                        video_ids.append(video_id)
                except KeyError as e:
                    logger.error('cannot parse video_id. reason:{}'.format(e))
            return video_ids
        except requests.Timeout:
            logger.error('time out request user page')
            return []
        except requests.ConnectionError:
            logger.error('connection error occur when request user ')
            return []
        except requests.HTTPError:
            logger.error('http error when request user page')
            return []
        except json.JSONDecodeError as e:
            logger.error('cannot decode response data to json object {}'.format(e))
            return []
        except KeyError as e:
            logger.error('cannot parse user info. reason:{}'.format(e))
            return []

    def track(self):
        now = datetime.now()
        with Pool(self._pool_size) as p:
            video_pages = p.map(VideoPage, self.new_videos)
        for video_page in video_pages:
            if not video_page.is_finish:
                pass
            # assert isinstance(video_page, VideoPage)
            t = Tempor(video_page.video_id, now,
                       video_page.views, video_page.likes,
                       video_page.dislikes, video_page.comments)
            db.insert(t, is_commit=False)


while True:
    beg = time.time()
    ex = Instance()
    print("{} video cost {}".format(len(ex.new_videos), time.time() - beg))

# job_instance = None
#
# def tick():
#     job_instance.track()
#
# def single_scheduler(index):
#     global job_instance
#     job_instance = Instance()
#     scheduler = BlockingScheduler()
#     scheduler.add_executor('processpool')
#     scheduler.add_job(tick, 'interval', seconds=XConfig.TRACK_SPAN)
#     try:
#         scheduler.start()
#     except (KeyboardInterrupt, SystemExit):
#         print('process has exit!!!')
#         scheduler.shutdown()
#
#
# single_scheduler()
