# -*- coding: utf-8 -*-
import re
import os
import ssl
import sys

from requests.exceptions import ProxyError

ssl._create_default_https_context = ssl._create_unverified_context
import json
import time
import aiohttp
import asyncio
import chardet  # 字符集检测
import pdfminer
import threading
import logging
import async_timeout
import concurrent.futures
from yarl import URL
from scrapy.selector import Selector
from collections import Iterator
from config.Basic import Basic
from concurrent.futures import ThreadPoolExecutor
from asyncio_config.my_Requests import MyResponse
from concurrent.futures import wait, ALL_COMPLETED
from config.settings import PREFETCH_COUNT, TIME_OUT, X_MAX_PRIORITY, Mysql, IS_PROXY, IS_SAMEIP, Asynch, Waiting_time, \
    Delay_time, max_request, Agent_whitelist, retry_http_codes, UA_PROXY, Auto_clear, message_ttl

from config.settings import Rabbitmq
from library_tool.sugars import retrying

shutdown_lock = threading.Lock()


def count_time(func):
    def clocked(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        end = time.time()
        total_time = end - start
        print(f'{kwargs.get("callback")}方法运行完成，共计{total_time}秒')
        return result

    return clocked


class LoopGetter(object):
    def __init__(self):
        self.parse_thread_pool = ThreadPoolExecutor(Rabbitmq['async_thread_pool_size'])  # 数据处理线程池

        # 定义一个线程，运行一个事件循环对象，用于实时接收新任务
        self.new_loop = asyncio.new_event_loop()
        self.loop_thread = threading.Thread(target=self.start_loop, args=(self.new_loop,))
        self.loop_thread.setDaemon(True)
        self.loop_thread.start()

        # 定义一个线程，运行一个事件循环对象，用于实时接收新任务
        self.shutdown_loop = asyncio.new_event_loop()
        self.loop_shutdown = threading.Thread(target=self.start_loop, args=(self.shutdown_loop,))
        self.loop_shutdown.setDaemon(True)
        self.loop_shutdown.start()

        self.charset_code = re.compile(r'charset=(.*?)"|charset=(.*?)>|charset="(.*?)"', re.S)
        self.last_time = time.time()
        self.starttime = None
        self.start_run_time = time.time()

    def start_loop(self, loop):
        # 一个在后台永远运行的事件循环
        asyncio.set_event_loop(loop)
        loop.run_forever()

    def start_requests(self):
        pass

    def parse(self, response):
        pass

    def parse_only(self, body):
        pass

    def close_spider(self, **kwargs):
        pass


class Manager(Basic, LoopGetter):
    name = None
    spider_sign = None
    custom_settings = {}

    def __init__(self):
        LoopGetter.__init__(self)
        if self.custom_settings:
            Basic.__init__(self, queue_name=self.name, custom_settings=self.custom_settings, class_name='Manager')
            for varName, value in self.custom_settings.items():
                # s = globals().get(varName)
                if varName in globals().keys():
                    globals()[varName] = value
        else:
            Basic.__init__(self, queue_name=self.name, class_name='Manager')
        self.pages = int(sys.argv[1]) if len(sys.argv) > 1 else None
        self.logger.name = logging.getLogger(__name__).name
        self.num = PREFETCH_COUNT
        self.timeout = TIME_OUT
        self.x_max_priority = X_MAX_PRIORITY
        self.message_ttl = message_ttl
        self.mysql = Mysql
        self.is_proxy = IS_PROXY
        self.is_sameip = IS_SAMEIP
        self.asynch = Asynch
        self.waiting_time = Waiting_time
        self.delay_time = Delay_time
        self.max_request = max_request

    def Environmental_judgment(self):
        if self.operating_system == 'linux' and self.pages and len(sys.argv) > 1:
            return True
        else:
            return False

    def open_spider(self, spider_name: str):
        """开启spider第一步检查状态"""
        data = self.select(table='spiderlist_monitor', columns=['owner', 'remarks'],
                           where=f"""spider_name = '{spider_name}'""")
        if data:
            self.owner = self.per_json(data, '[0].owner')
            self.source = self.per_json(data, '[0].remarks')
        if data and self.operating_system == 'linux' and self.pages and len(sys.argv) > 1:
            self.update(table='spiderlist_monitor', set_data={'is_run': 'yes', 'start_time': self.now_time()},
                        where=f"""`spider_name` = '{spider_name}'""")
            if not self.monitor:
                self.send_start_info()
        elif not data:
            self.logger.info(
                'If you need to turn on increment, please register and try to run again. If not, please ignore it')
            self.logger.info(f'Crawler service startup for {spider_name}')
        self.logger.info('Crawler program starts')
        return True

    def make_start_request(self, start_fun: {__name__}):
        try:
            start_task = self.__getattribute__(start_fun.__name__)()
            if isinstance(start_task, Iterator):
                for s in start_task:
                    self.send_message(message=s)
        except:
            import traceback
            traceback.print_exc()

    def run(self):
        """启动spider的入口"""
        # package = __import__(self.path+ self.queue_name.replace('ysh_', ''), fromlist=['None'])
        # temp_class = getattr(package, self.queue_name.replace('ysh_', ''))
        # self.duixiang = temp_class()
        # self.duixiang = actuator.LoadSpiders()._spiders[spider_name]()
        if Auto_clear:  # 如果自动清空队列
            try:
                self.delete_queue(queue_name=self.queue_name)
                self.logger.info('The queue has been cleared automatically')
            except:
                self.logger.error('The automatic queue clearing failed', exc_info=True)
                if self.pages:
                    self.send_close_info()
        self.starttime = self.now_time()
        self.start_time = time.time()
        status = self.open_spider(spider_name=self.name)
        if status:
            if 'Breakpoint' in self.custom_settings.keys():  # 如果修改了开启断点参数
                if Asynch:  # 如果是异步生产（一边生产一边消费）
                    self.async_thread_pool.submit(self.make_start_request, start_fun=self.start_requests)

                else:  # 如果不需要异步生产（等生产完之后再开始消费）
                    self.async_thread_pool.submit(self.make_start_request, start_fun=self.start_requests)
                    wait(fs=self.work_list, timeout=None, return_when=ALL_COMPLETED)

                    # start_th(fun_lists=[self.start_requests], queue_name=self.name,
                    #          signal=self.custom_settings['Breakpoint'])


            else:  # 如果是默认断点配置
                if Asynch:  # 如果是异步生产（一边生产一边消费）
                    self.async_thread_pool.submit(self.make_start_request, start_fun=self.start_requests)

                else:  # 如果不需要异步生产（等生产完之后再开始消费）
                    self.work_list.append(
                        self.async_thread_pool.submit(self.make_start_request, start_fun=self.start_requests))
                    wait(fs=self.work_list, timeout=None, return_when=ALL_COMPLETED)

            asyncio.run_coroutine_threadsafe(self.shutdown_spider(spider_name=self.name),
                                             self.shutdown_loop)  # 开启监控队列状态
            self.consumer_status = self.async_thread_pool.submit(self.get_message)  # 开启消费者
            self.logger.info('Consumer thread open ' + str(self.consumer_status))
            self.work_list.append(self.consumer_status)
            wait(fs=self.work_list, timeout=None, return_when=ALL_COMPLETED)

        elif status == False:
            return

    async def shutdown_spider(self, spider_name):
        """监控队列及运行状态"""
        while 1:
            now_time = time.time()
            self.logger.debug(
                f"It's been {round(now_time - self.last_time, 2)} seconds since the last time I took data from the queue. The remaining number of queues is {self.getMessageCount(queue_name=self.queue_name)}")
            if self.monitor and self.right_count:
                pwd = os.getcwd()
                spider_path = os.path.join(pwd, f'{self.name}.py')
                item = {'task_name': spider_path, 'local_time': self.now_time()}
                try:
                    self.producer.send('is_real_run_test', json.dumps(item).encode('utf-8'))
                    self.producer.flush()
                    self.logger.info(f'检测到有新数据，任务已入队列, {item}')
                except:
                    self.logger.error('kafka生产者异常', exc_info=True)
                break
            elif self.monitor and now_time - self.start_run_time >= 3600:
                self.logger.info('一小时未结束运行，检测到没有新数据')
                self.send_start_info()
                self.send_close_info()
                break
            elif ((now_time - self.last_time >= self.waiting_time) and (
                    self.getMessageCount(queue_name=self.queue_name) == 0)):
                if self.Environmental_judgment() and not self.monitor:
                    self.send_close_info()
                try:
                    self.update(table='spiderlist_monitor', set_data={'is_run': 'no', 'end_time': self.now_time()},
                                where=f"""`spider_name` = '{spider_name}'""")
                except:
                    self.logger.info("Crawler closed, abnormal update of running status，Forced closing！", exc_info=True)
                if self.monitor and not self.right_count:
                    self.logger.info('检测到没有新数据')
                    self.send_start_info()
                    self.send_close_info()
                break
            time.sleep(self.delay_time)
        self.finished_info(self.starttime, self.start_time)  # 完成时的日志打印
        os._exit(0)  # 暂时重新启用，待观察

    @retrying(stop_max_attempt_number=Rabbitmq['max_retries'])  # 重试装饰器
    def get_message(self, befor_fun='reconnect', befor_parmas='conn'):
        """消费者"""
        self.logger.info('开始消费')
        with self.get_connection() as connection:
            channel = connection.channel()
            channel.queue_declare(queue=self.queue_name,
                                  arguments={'x-max-priority': (Rabbitmq['X_MAX_PRIORITY'] or 0),
                                             'x-queue-mode': 'lazy', 'x-message-ttl': Rabbitmq['message_ttl']},
                                  durable=True)
            channel.basic_qos(prefetch_count=1)  # 让rabbitmq不要一次将超过1条消息发送给work
            channel.basic_consume(queue=self.queue_name, on_message_callback=self.Requests)
            channel.start_consuming()

    def Requests(self, ch, method, properties, body):
        """消息处理函数"""
        self.last_time = time.time()
        self.num -= 1
        ch.basic_ack(delivery_tag=method.delivery_tag)  # 手动发送ack,如果没有发送,队列里的消息将会发给下一个worker
        while self.num < 0:
            self.logger.debug(f'The request queue is full，进程号为：{os.getpid()}')
            time.sleep(1)
        flag = self.is_json(body.decode('utf-8'))
        if not flag:  # 判断是否为请求消息，如果不是的话
            self.parse_thread_pool.submit(self.parse_only, body=body.decode('utf-8'))  # 多线程数据处理

            # fun_lists = self.parse_only(body=body.decode('utf-8'))
            # if isinstance(fun_lists, Iterator):
            #     for p in fun_lists:
            #         self.async_send_message(message=p)
            self.num += 1
        if flag:  # 判断是否为请求消息，如果是的话
            self.make_params(body)

    def make_params(self, body):
        """获取并处理有关的参数"""
        contents = json.loads(body.decode('utf-8'))
        callback_demo = contents.get('callback')
        is_encode = contents.get('is_encode')
        url = contents.get('url')
        headers = contents.get('headers')
        params = contents.get('params')
        data = contents.get('data')
        json_params = contents.get('json_params')
        timeout = contents.get('timeout')
        dont_filter = contents.get('dont_filter')
        encoding = contents.get('encoding')
        meta = contents.get('meta')
        for k, v in meta.items():
            if self.is_json(v) and not isinstance(v, dict):
                meta[k] = json.loads(v, object_hook=self.handle)
        level = contents.get('level')
        proxy = contents.get('proxy')
        meta['proxy'] = proxy if proxy and self.is_sameip else meta.get('proxy')
        verify_ssl = contents.get('verify_ssl')
        allow_redirects = contents.get('allow_redirects')
        is_file = contents.get('is_file')
        retry_count = 0 if contents.get('retry_count') == None else contents.get('retry_count')
        is_change = contents.get('is_change')
        param = meta, meta.get('proxy') if (meta if meta else {}) else proxy
        meta = param[0]
        proxy = param[1] if meta.get('proxy') else proxy
        ignore_ip = contents.get('ignore_ip')
        methods = 'POST' if contents.get('method') == 'POST' else 'GET'
        timeout = timeout if timeout else self.timeout
        asyncio.run_coroutine_threadsafe(
            self.make_Requests(method=methods, is_encode=is_encode, url=url, body=body,
                               headers=headers, params=params, data=data, json_params=json_params,
                               timeout=timeout, callback=callback_demo, dont_filter=dont_filter,
                               encoding=encoding, meta=meta, level=level, proxy=proxy,
                               verify_ssl=verify_ssl, is_file=is_file, retry_count=retry_count,
                               is_change=is_change, allow_redirects=allow_redirects,
                               ignore_ip=ignore_ip, request_info=body.decode('utf-8')), self.new_loop)

    async def request_preprocess(self, body, url, proxy, is_change, meta, req_id, params, data, json_params, headers):
        """请求预处理"""
        new_body = json.loads(body.decode('utf-8'))
        self.is_proxy = True if (len([False for i in Agent_whitelist if
                                      i in url]) == 0) and IS_PROXY == True else False
        if self.is_proxy == False:
            proxy = None
        elif self.is_proxy and ((proxy == None) or (is_change)):
            proxy = await self.asy_rand_choi_pool()
            if self.is_sameip:
                meta['proxy'] = proxy
                new_body['meta']['proxy'] = proxy
        if self.is_proxy and proxy:
            self.send_log(req_id=req_id, code='10', log_level='INFO', url=url, message='取代理成功',
                          formdata=self.dic2params(params, data, json_params), show_url=meta.get('show_url'))
        elif self.is_proxy and proxy == None:
            self.send_log(req_id=req_id, code='11', log_level='WARN', url=url, message='取代理失败',
                          formdata=self.dic2params(params, data, json_params), show_url=meta.get('show_url'))
        if isinstance(headers, dict):
            headers['User-Agent'] = await self.get_ua() if UA_PROXY else headers['User-Agent']
        return new_body, proxy, headers, meta

    async def make_Requests(self, method='GET', url=None, body=None, headers=None, params=None, data=None,
                            json_params=None, cookies=None, timeout=None, callback=None, dont_filter=False,
                            encoding=None, meta=None, level=0, request_info=None, proxy=None, verify_ssl=None,
                            allow_redirects=True, is_file=False, retry_count=0, is_change=False, is_encode=None,
                            ignore_ip=False):
        """请求处理函数"""
        req_id = self.get_inttime()
        try:
            # 监测环境下，进行标书请求去重
            if self.pages and not dont_filter:
                if await self.contarst_data(url):
                    self.num += 1
                    return
            new_body, proxy, headers, meta = await self.request_preprocess(body, url, proxy, is_change, meta, req_id,
                                                                           params, data, json_params, headers)
            while retry_count < self.max_request:
                new_body['proxy'] = proxy = proxy if not ignore_ip else None
                try:
                    self.send_log(req_id=req_id, code='01', log_level='INFO', url=url, message='即将发送请求',
                                  formdata=self.dic2params(params, data, json_params), show_url=meta.get('show_url'))
                    text = ''
                    with async_timeout.timeout(timeout=timeout):
                        async with aiohttp.ClientSession(headers=headers, conn_timeout=timeout,
                                                         cookies=cookies) as session:
                            if method == 'GET':
                                async with session.get(url=URL(url, encoded=True) if is_encode else url, params=params,
                                                       data=data, json=json_params, headers=headers, proxy=proxy,
                                                       verify_ssl=verify_ssl, timeout=timeout,
                                                       allow_redirects=allow_redirects) as response:
                                    res = await response.read()
                                    await self.infos(response.status, method, url, req_id, params, data, json_params,
                                                     meta.get('show_url'))  # 打印日志
                                    text = await self.deal_code(res=res, body=body, is_file=is_file, encoding=encoding)

                            elif method == "POST":
                                async with session.post(url=URL(url, encoded=True) if is_encode else url, params=params,
                                                        data=data, json=json_params, headers=headers, proxy=proxy,
                                                        verify_ssl=verify_ssl, timeout=timeout,
                                                        allow_redirects=allow_redirects) as response:
                                    res = await response.read()
                                    await self.infos(response.status, method, url, req_id, params, data, json_params,
                                                     meta.get('show_url'))  # 打印日志
                                    text = await self.deal_code(res=res, body=body, is_file=is_file, encoding=encoding)
                    if text:
                        if '您的授权设置可能有问题' in text and '您当前的客户端IP地址为' in text:
                            raise ProxyError(f'{proxy}代理并发数超限制')
                    response_last = MyResponse(url=url, headers=response.headers, data=data,
                                               cookies=response.cookies, meta=meta, retry_count=retry_count,
                                               text=text, content=res, status_code=response.status,
                                               request_info=request_info, proxy=proxy, level=level,
                                               log_info={'req_id': req_id, 'params': params, 'data': data,
                                                         'json_params': json_params})
                    await self.Iterative_processing(method=method, callback=callback,
                                                    response_last=response_last, body=body, level=level,
                                                    retry_count=retry_count, req_id=req_id)
                    break
                except (aiohttp.ClientProxyConnectionError, aiohttp.ServerTimeoutError, TimeoutError,
                        concurrent.futures._base.TimeoutError, aiohttp.ClientHttpProxyError,
                        aiohttp.ServerDisconnectedError, aiohttp.ClientConnectorError, aiohttp.ClientOSError,
                        aiohttp.ClientPayloadError) as e:
                    retry_count += 1
                    await self.retry(method, url, retry_count, repr(e), new_body, req_id, params, data, json_params,
                                     meta.get('show_url'))
                    if self.is_proxy:
                        proxy = await self.asy_rand_choi_pool()
                        if self.is_sameip:
                            meta['proxy'] = proxy
                            new_body['meta']['proxy'] = proxy

                except pdfminer.pdfparser.PDFSyntaxError as e:
                    response_last = MyResponse(url=url, headers={}, data=data, cookies=cookies, meta=meta,
                                               text='PDF无法打开或失效', content=b'', status_code=200, proxy=proxy,
                                               log_info={'req_id': req_id, 'params': params, 'data': data,
                                                         'json_params': json_params})
                    await self.Iterative_processing(method=method, callback=callback, response_last=response_last,
                                                    body=body, level=level, retry_count=retry_count, req_id=req_id)

                except Exception as e:
                    if (not self.is_proxy) and (self.max_request):
                        retry_count += 1
                        await self.retry(method, url, retry_count, repr(e), new_body, req_id, params, data, json_params,
                                         meta.get('show_url'))
                        self.logger.error(repr(e) + ' Returning to the queue ' + str(new_body), exc_info=True)
                    else:
                        retry_count += 1
                        mess = json.loads(body.decode('utf-8'))
                        mess['is_change'] = True
                        mess['retry_count'] = retry_count
                        self.async_send_message(message=json.dumps(mess))
                        self.logger.error(repr(e) + ' Returning to the queue ' + str(new_body), exc_info=True)
                        break
            else:
                response_last = MyResponse(url=url, headers={}, data={}, cookies=None, meta=meta,
                                           retry_count=retry_count,
                                           text='', content=b'', status_code=None, request_info=request_info,
                                           proxy=proxy, level=level,
                                           log_info={'req_id': req_id, 'params': params, 'data': data,
                                                     'json_params': json_params})
                await self.Iterative_processing(method=method, callback=callback, response_last=response_last,
                                                body=body, level=level, retry_count=retry_count, req_id=req_id)
        except Exception as e:
            import traceback
            traceback.print_exc()
        self.num += 1

    async def contarst_data(self, url):
        url_sha1 = self.url2sha1(url)
        t_num = str(int(url_sha1[-2:], 16) % 16)
        url_sha1 = self.select(table=f't_bidding_filter_{t_num}', columns=['url_sha1'], where=f"url_sha1='{url_sha1}'")
        if url_sha1:
            self.logger.info(f'Data already exists, the request has been skipped：{url}')
            return True

    async def deal_code(self, res, body, is_file, encoding):  # 编码处理函数
        if is_file:
            text = None
            return text
        charset_code = chardet.detect(res[0:1])['encoding']
        # charset_code = self.deal_re(self.charset_code.search(str(res)))
        if encoding:
            charset_code = encoding
        if charset_code:
            try:
                text = res.decode(charset_code)
                if not self.is_contain_chinese(text):
                    text = await self.cycle_charset(res, body)  # 此处存疑
                return text
            except (UnicodeDecodeError, TypeError, LookupError):
                text = await self.cycle_charset(res, body)
                if not text:
                    text = str(res, charset_code, errors='replace')
                return text
            except Exception as e:
                self.logger.error(repr(e) + ' Decoding error ' + body.decode('utf-8'), exc_info=True)
        else:
            text = await self.cycle_charset(res, body)
            return text

    async def cycle_charset(self, res, body):  # 异常编码处理函数
        charset_code_list = ['utf-8', 'gbk', 'gb2312', 'utf-16']
        for code in charset_code_list:
            try:
                text = res.decode(code)
                return text
            except UnicodeDecodeError:
                continue
            except Exception as e:
                self.logger.error(repr(e) + ' Decoding error ' + body.decode('utf-8'), exc_info=True)

    async def Iterative_processing(self, method, callback, response_last, body, level, retry_count,
                                   req_id):  # 迭代器及异常状态码处理函数
        mess = json.loads(body.decode('utf-8'))
        if (response_last.status_code != 200) and (response_last.status_code in retry_http_codes) and (
                retry_count < self.max_request):
            mess['retry_count'] = retry_count = int(retry_count) + 1
            if self.is_proxy:
                mess['proxy'] = await self.asy_rand_choi_pool()
                if self.is_sameip:
                    mess['meta']['proxy'] = mess['proxy']
            if (retry_count < self.max_request):
                self.async_send_message(message=json.dumps(mess))
                await self.retry(method, response_last.url, str(retry_count),
                                 f'Wrong status code {response_last.status_code}', str(mess),
                                 req_id, mess.get('params'), mess.get('data'), mess.get('json_params'),
                                 mess['meta'].get('show_url'))
                self.exc_count += 1
            elif (retry_count == self.max_request):
                self.logger.debug(f'Give up <{body.decode("utf-8")}>')
                self.fangqi_count += 1
                response_last.retry_count = retry_count
                await self.__deal_fun(callback=callback, response_last=response_last)
            return

        if (response_last.status_code != 200) and (response_last.status_code != None) and (
                response_last.status_code not in retry_http_codes):
            if int(retry_count) < 3:
                mess['retry_count'] = retry_count = int(retry_count) + 1
                if self.is_proxy:
                    mess['proxy'] = await self.asy_rand_choi_pool()
                    if self.is_sameip:
                        mess['meta']['proxy'] = mess['proxy']
                self.async_send_message(message=json.dumps(mess))
                await self.retry(method, response_last.url, str(retry_count),
                                 f'Other wrong status code {response_last.status_code}', str(mess),
                                 req_id, mess.get('params'), mess.get('data'), mess.get('json_params'),
                                 mess['meta'].get('show_url'))
                self.other_count += 1
            else:
                self.logger.debug(f'Give up <{body.decode("utf-8")}>')
                self.fangqi_count += 1
                response_last.retry_count = retry_count
                await self.__deal_fun(callback=callback, response_last=response_last)
            return

        if (retry_count == self.max_request):
            self.logger.debug(f'Give up <{body.decode("utf-8")}>')
            self.fangqi_count += 1
            response_last.retry_count = retry_count
        await self.__deal_fun(callback=callback, response_last=response_last)

    # @count_time
    async def __deal_fun(self, callback, response_last):
        try:
            if response_last.text:
                response_last.xpath = Selector(response=response_last).xpath
            if self.__getattribute__(callback)(response=response_last):
                for c in self.__getattribute__(callback)(response=response_last):
                    # if c.meta == {}:
                    c.meta['proxy'] = response_last.meta.get('proxy')
                    # else:
                    #     c.meta = dict(response_last.meta, **c.meta)
                    # if int(response_last.level) + 1 > self.x_max_priority:
                    #     c.level = self.x_max_priority
                    # else:
                    #     c.level = int(response_last.level) + 1  # 优先级自动递增，适用yield
                    self.async_send_message(message=c)
        except Exception as e:
            self.exec_count += 1
            self.send_log(req_id=response_last.log_info['req_id'], code='32', log_level='ERROR', url=response_last.url,
                          message='爬虫逻辑报错',
                          formdata=self.dic2params(response_last.log_info['params'], response_last.log_info['data'],
                                                   response_last.log_info['json_params']),
                          show_url=response_last.meta.get('show_url'))
            # if self.exec_count >= 100 and self.pages:
            #     import os
            #     self.finished_info(self.starttime, self.start_time, exec_info=True)  # 完成时的日志打印
            #     if self.pages:
            #         self.send_close_info()
            #     os._exit(0)
            self.logger.error(e, exc_info=True)

    async def infos(self, status, method, url, req_id, params, data, json_params, show_url):  # 日志函数
        self.request_count += 1
        self.logger.info(f'Mining ({status}) <{method} {url}>')
        if str(status) == '200':
            self.success_code_count += 1
            self.logger.debug(f'Catched from <{status} {url}>')
            self.send_log(req_id=req_id, code='20', log_level='INFO', url=url, message='请求成功',
                          formdata=self.dic2params(params, data, json_params), show_url=show_url)
        if int(status) >= 400:
            self.send_log(req_id=req_id, code='21', log_level='WARN', url=url, message='http状态码大于等于400',
                          formdata=self.dic2params(params, data, json_params), show_url=show_url)

    async def retry(self, method, url, retry_count, abnormal, message, req_id, params, data, json_params,
                    show_url):  # 重试日志函数
        self.logger.debug(
            f'Retrying <{method} {url}> (failed {retry_count} times): {abnormal} {message}')
        self.send_log(req_id=req_id, code='25', log_level='WARN', url=url, message=f'第{retry_count}次重试请求',
                      formdata=self.dic2params(params, data, json_params), show_url=show_url)
        self.wrong_count += 1