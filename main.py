import os
import time
import winreg
import datetime
import requests
import threading
import subprocess

from pathlib import Path
from typing import List, Sequence

import sqlalchemy
from sqlalchemy import inspect, types, select
from sqlalchemy.orm import Session, DeclarativeBase, Mapped, mapped_column

from spdlogger import logger, LoggerUtil


os.system("cls")
os.system("chcp 65001")


class win32proxy:
    def __init__(self):
        self.__path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        self.__INTERNET_SETTINGS = winreg.OpenKeyEx(winreg.HKEY_CURRENT_USER, self.__path, 0, winreg.KEY_ALL_ACCESS)

    def get_proxy(self):
        ip_port = str()
        if self.is_open_proxy():
            try:
                ip_port = winreg.QueryValueEx(self.__INTERNET_SETTINGS, "ProxyServer")[0]
                return str(ip_port)
            except Exception as e:
                print(e)
        return str()

    def is_open_proxy(self):
        try:
            if winreg.QueryValueEx(self.__INTERNET_SETTINGS, "ProxyEnable")[0] == 1:
                return True
        except Exception as e:
            print(e)
        return False


class MangaLocalDatabase:
    #
    class Base(DeclarativeBase):
        pass

    def __init__(self, sqlite_file_path: str, logger: LoggerUtil.Logger):
        self._logger: LoggerUtil.Logger = logger
        self._dbfile = Path(f"db.nosync/{sqlite_file_path}")

        self._dbfile.resolve().parent.mkdir(parents=True, exist_ok=True)

        self.engine: sqlalchemy.Engine = sqlalchemy.create_engine(f"sqlite:///{self._dbfile.resolve().as_posix()}")

        if (
            not inspect(self.engine).has_table("files")  #
            or not inspect(self.engine).has_table("metadata")
        ):
            self._logger.info(f"初始化数据库({self._dbfile.resolve().as_posix()})")
            MangaLocalDatabase.Base.metadata.create_all(self.engine)

        else:
            self._logger.info(f"连接数据库({self._dbfile.resolve().as_posix()})")

    def GetDbFilePath(self):
        return self._dbfile.resolve()

    class FileTableItem(Base):
        __tablename__ = "files"
        index: Mapped[int] = mapped_column(types.INTEGER, primary_key=True)
        filename: Mapped[str] = mapped_column(types.TEXT)
        basepath: Mapped[str] = mapped_column(types.TEXT)
        url: Mapped[str] = mapped_column(types.TEXT)
        status: Mapped[int] = mapped_column(types.INTEGER)

        @staticmethod
        def Create(
            filename: str,
            basepath: str,
            url: str,
        ):
            return MangaLocalDatabase.FileTableItem(
                filename=filename,
                basepath=basepath,
                url=url,
                status=0,
            )

    class MetadataTableItem(Base):
        __tablename__ = "metadata"
        index: Mapped[int] = mapped_column(types.INTEGER, primary_key=True)
        name: Mapped[str] = mapped_column(types.TEXT)
        context: Mapped[str] = mapped_column(types.TEXT)
        url: Mapped[str] = mapped_column(types.TEXT)
        status: Mapped[int] = mapped_column(types.INTEGER)

        @staticmethod
        def Create(
            name: str,
            context: str,
            url: str,
            status: int,
        ):
            return MangaLocalDatabase.MetadataTableItem(
                name=name,
                context=context,
                url=url,
                status=status,
            )


class RequsetCountLock:
    def __init__(self, num: int) -> None:
        self._queue: List[datetime.datetime] = []
        self._lock = threading.Lock()
        self._num = num
        self._logger = logger.ObjLogger(self)

    def ReleaseTime(self):
        if len(self._queue) == 0:
            return 0
        return (self._queue[0] - datetime.datetime.now()).seconds

    def Ready(self):
        self._lock.acquire()
        ret = True
        while len(self._queue) >= self._num:
            if self._queue[0] > datetime.datetime.now():
                ret = False
                break
            self._queue.pop(0)
            ret = True
            break
        self._lock.release()
        return ret

    def CountAdd(self):
        self._lock.acquire()
        self._queue.append(datetime.datetime.now() + datetime.timedelta(seconds=61))
        self._lock.release()

    def Refresh(self):
        self._lock.acquire()
        while len(self._queue) != 0:
            if self._queue[0] > datetime.datetime.now():
                break
            self._queue.pop(0)
            continue
        self._lock.release()
        return

    def __str__(self) -> str:
        self.Refresh()
        return f"[{len(self._queue)}/{self._num}]"


globle_download_request_lock = RequsetCountLock(99)


class MultiCurl:
    #
    root = "./dl.nosync"

    class ProcessInfo:
        def __init__(
            self,
            db_item: MangaLocalDatabase.FileTableItem,
            basecmd: str,
            logger: LoggerUtil.Logger,
        ) -> None:
            self.logger = logger
            self.orm: MangaLocalDatabase.FileTableItem = db_item

            url = self.orm.url

            if not url.startswith("http"):
                self.logger.error(f"非法URL {url}")
                self.orm.status = -255
                return

            basepath = self.orm.basepath
            filename = self.orm.filename
            fullpath = Path(f"{MultiCurl.root}/{basepath}/{filename}")
            fullpath.parent.mkdir(parents=True, exist_ok=True)

            if fullpath.exists() and fullpath.is_dir():
                raise TypeError(f"文件保存路径({fullpath.as_posix()})被目录占用")

            if fullpath.exists() and fullpath.is_file():
                self.logger.info(f"删除文件({fullpath.as_posix()})")
                fullpath.unlink()

            self.cmd = f'{basecmd} -o "{fullpath.as_posix()}" {url}'

            self.process: subprocess.Popen = self._Run()
            self.timeout = datetime.datetime.now() + datetime.timedelta(seconds=120)
            self.orm.status = 1
            self.logger.info(f"创建进程(PID={str(self.process.pid).zfill(5)}) {self.process.args}")

        def _Run(self):
            return subprocess.Popen(
                self.cmd,
                shell=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        def Restart(self):
            if self.process.poll() is None:
                self.process.kill()
            self.process = self._Run()
            self.timeout = datetime.datetime.now() + datetime.timedelta(seconds=120)
            self.logger.info(f"重试进程({str(self.process.pid).zfill(5)}) {self.process.args}")
            return

    def __init__(self, database: MangaLocalDatabase, proxy: str) -> None:
        self.logger = logger.ObjLogger(self)

        self.proxy: str = ""
        if len(proxy) != 0:
            self.proxy = f" -x {proxy}"
        self.max_process_num = 20
        self.basecmd = f"./bin/curl{self.proxy}"
        self.process_list: List[MultiCurl.ProcessInfo] = []
        self.requset_lock = globle_download_request_lock
        self.database = database
        self.session = Session(self.database.engine)
        self._is_session_close = False

    def _Get(self, value: int):
        TableItem = MangaLocalDatabase.FileTableItem
        items: Sequence[MangaLocalDatabase.FileTableItem] = self.session.scalars(
            select(
                TableItem,
            ).where(TableItem.status == value),
        ).all()
        return items

    def _GetNotFinish(self) -> List[MangaLocalDatabase.FileTableItem]:
        return list(self._Get(1))

    def _GetNotStart(self) -> List[MangaLocalDatabase.FileTableItem]:
        return list(self._Get(0))

    def Run(self):
        if self._is_session_close is True:
            self.session = Session(self.database.engine)
        #
        not_finish_items = self._GetNotFinish()
        not_finish_count = len(not_finish_items)
        if not_finish_count != 0:
            self.logger.info(f"继续 {not_finish_count} 个未完成任务")
            self._TaskLoop(not_finish_items)

        not_start_items = self._GetNotStart()
        not_start_count = len(not_start_items)
        if not_start_count != 0:
            self.logger.info(f"开始 {not_start_count} 个新下载任务")
            self._TaskLoop(not_start_items)

        self.session.close()
        self._is_session_close = True
        return

    def _AddTask(self, tasks: List[MangaLocalDatabase.FileTableItem]) -> None:
        while True:
            if len(tasks) == 0:
                return
            if len(self.process_list) >= self.max_process_num:
                return
            # 限制每分钟请求次数
            if not self.requset_lock.Ready():
                self.logger.warn(f"等待下载API请求次数 {self.requset_lock.ReleaseTime()}s")
                time.sleep(1)
                return
            task = tasks[0]
            # 创建下载进程
            process = MultiCurl.ProcessInfo(
                task,
                self.basecmd,
                self.logger,
            )
            self.session.commit()
            if task.status != 1:
                continue
            # 增加到当前任务列表
            self.process_list.append(process)
            self.requset_lock.CountAdd()
            tasks.pop(0)
            continue

    def _TaskLoop(self, tasks: List[MangaLocalDatabase.FileTableItem]) -> None:
        while True:
            task_count = len(tasks)
            self._AddTask(tasks)
            if self._ProcessLoop(task_count):
                continue
            if not task_count:
                break

        self.logger.info("下载完成")
        return

    def _ProcessLoop(self, has_task: int) -> bool:
        while True:
            exitcode_list: List[str] = list()

            # 获取进程退出返回值
            for pinfo in self.process_list:
                exitcode = pinfo.process.poll()

                # 任务正常退出
                if exitcode is not None and exitcode == 0:
                    exitcode_list.append(str(exitcode))
                    continue

                # 任务异常退出
                if exitcode is not None:
                    pinfo.Restart()
                    exitcode_list.append("!")
                    continue

                # 任务超时未完成
                if pinfo.timeout < datetime.datetime.now():
                    pinfo.Restart()
                    exitcode_list.append("?")
                    continue

                exitcode_list.append("-")
                continue

            # 显示进程运行状态
            if len(exitcode_list) != 0:
                msg = str()
                for s in exitcode_list:
                    msg += s + ""
                if len(msg) < self.max_process_num:
                    msg += " " * (self.max_process_num - len(msg))
                self.logger.debug(f"[{msg}] 任务容量[{len(exitcode_list)}/{self.max_process_num}] 请求容量{self.requset_lock}")
                time.sleep(1)

            # 处理已退出进程
            for pinfo in self.process_list:
                if pinfo.process.poll() is None:
                    continue
                pinfo.orm.status = 255
                self.session.commit()
                self.process_list.remove(pinfo)

            # 队列空闲还有剩余任务时返回
            if (has_task != 0) and (len(self.process_list) < self.max_process_num):
                return True

            # 无剩余任务队列完成时完成
            if len(self.process_list) == 0:
                return False

            continue


class CopymangaItem:
    #
    class AuthorItem:
        def __init__(self) -> None:
            self.name: str = ""
            self.path_word: str = ""

        @staticmethod
        def FromMap(author: List[dict] | None) -> "List[CopymangaItem.AuthorItem]":
            anthor_list: List[CopymangaItem.AuthorItem] = []
            if author is None:
                return anthor_list
            for i in author:
                obj = CopymangaItem.AuthorItem()
                obj.name = str(i.get("name"))
                obj.path_word = str(i.get("path_word"))
                anthor_list.append(obj)
            return anthor_list

        def __str__(self) -> str:
            return f'<{CopymangaItem.AuthorItem.__name__} name="{self.name}" path="{self.path_word}">'

    class ChapterItem:
        def __init__(self) -> None:
            self.index: int = 0
            self.name: str = ""
            self.uuid: str = ""
            self.size: int = 0
            self.comic_id: str = ""
            self.comic_path_word: str = ""
            self.group_id: str = ""
            self.group_path_word: str = ""
            self.datetime_created: str = ""
            self.prev_uuid: str = ""
            self.next_uuid: str = ""

    class GroupItem:
        def __init__(self) -> None:
            self.name: str = ""
            self.path_word: str = ""
            self.chapters: List[CopymangaItem.ChapterItem] = []

    class MangaItem:
        def __init__(self) -> None:
            self.name: str = ""
            self.alias: str = ""
            self.path_word: str = ""
            self.cover: str = ""
            self.author: List[CopymangaItem.AuthorItem] = []
            self.status: str = ""
            self.uuid: str = ""
            self.groups: List[CopymangaItem.GroupItem] = []

        def FormatAuthor(self):
            fmt: str = ""
            for i in self.author:
                fmt += i.name + ","
            return fmt[:-1]

        def __str__(self) -> str:
            return f'<{CopymangaItem.MangaItem.__name__} name="{self.name}" path="{self.path_word}">'


class ApiRequsetLock:
    def __init__(self, num: int) -> None:
        self._queue: List[datetime.datetime] = []
        self._lock = threading.Lock()
        self._num = num
        self._logger = logger.ObjLogger(self)

    def WaitQueue(self):
        if self._lock.locked():
            self._logger.debug("等待API线程锁...")

        self._lock.acquire()

        once_msg = False
        while len(self._queue) >= self._num:
            if self._queue[0] >= datetime.datetime.now():
                if once_msg is False:
                    self._logger.debug(f"等待API请求次数... {(self._queue[0] - datetime.datetime.now()).seconds}s")
                    once_msg = True
                time.sleep(1)
                continue
            self._queue.pop(0)
            continue

        self._queue.append(datetime.datetime.now() + datetime.timedelta(seconds=61))

        self._lock.release()
        return

    def Refresh(self):
        while len(self._queue) != 0:
            if self._queue[0] > datetime.datetime.now():
                break
            self._queue.pop(0)
            continue
        return

    def __str__(self) -> str:
        self.Refresh()
        return f"[{len(self._queue)}/{self._num}]"


globle_copymanga_api_lock = ApiRequsetLock(15)


class CopymangaTask:
    #
    def __init__(self, kw: str = "") -> None:
        self.logger = logger.ObjLogger(self)

        self.host: str = "mangacopy.com"
        self.proxy: None | dict = None
        self.header = {
            "User-Agent": "duoTuoCartoon/3.2.4 (iPhone; iOS 18.0.1; Scale/3.00) iDOKit/1.0.0 RSSX/1.0.0",
            "version": "2025.10.12",
            "region": "0",
            "webp": "1",
            "platform": "1",
            "referer": "https://www.copymanga.com/",
            "use_oversea_cdn": "1",
            "use_webp": "1",
        }

        sys_proxy = win32proxy().get_proxy()
        if sys_proxy:
            self.logger.info(f"使用系统代理 {sys_proxy}")
            self.proxy = {"https": f"http://{sys_proxy}"}

        self.manga: CopymangaItem.MangaItem = CopymangaItem.MangaItem()
        self.api_lock = globle_copymanga_api_lock

        pathword: str = kw

        if len(kw) == 0:
            while True:
                self.logger.info(f"任务未定义漫画id, 搜索关键词(str)=")
                r = self.Search(input())
                if r is None:
                    continue
                pathword = r
                break

        if self._InitInfo(pathword) is False:
            self.logger.error(f"输入的漫画(id={kw})不存在")
            raise ValueError

        self.local_storage = Path(f"./dl.nosync/{self.manga.name}")

        self.database: MangaLocalDatabase = MangaLocalDatabase(
            f"{self.manga.path_word}.db",
            self.logger,
        )

    def _ApiGet(self, url, msg: str = "") -> dict:
        self.api_lock.WaitQueue()
        err = 0
        while True:
            try:
                self.logger.debug(f"{msg}请求 {url} 请求容量{self.api_lock}")
                ret = requests.get(url, headers=self.header, proxies=self.proxy)
                break
            except Exception as e:
                err += 1
                self.logger.warn(f"{msg}连接失败, 重试第{err})次")
                self.logger.warn(f"{msg}| {e}")
            if err > 4:
                self.logger.error(f"{msg}无法请求 {url}.")
                raise ConnectionError

        if ret.status_code < 200 or ret.status_code > 299:
            self.logger.error(f"{msg}请求失败 HTTP{ret.status_code}.")
            raise ValueError

        results = self._CheckApiResults(ret.json())

        return results

    def _CheckApiResults(self, j: dict) -> dict:
        json_code: int | None = j.get("code")
        json_results: dict | None = j.get("results")
        if json_code is None or json_code != 200:
            raise ValueError(f"请求错误 {json_code}: {j.get('message')}")
        if json_results is None:
            raise ValueError(f"JSON不存在路径[/results]")
        return json_results

    def Search(self, kw: str) -> str | None:
        results = self._ApiGet(
            f"https://api.{self.host}/api/v3/search/comic?format=json&platform=3&q={kw}&limit=10&offset=0",
            "",
        )

        json_results_list: List[dict] | None = results.get("list")
        if json_results_list is None:
            raise ValueError(f"JSON不存在路径[/results/list]")

        if len(json_results_list) == 0:
            self.logger.warn(f"未搜索到任何内容")
            return None

        manga_list: List[str] = []
        for i, item in enumerate(json_results_list):
            name: str | None = item.get("name")
            path_word: str | None = item.get("path_word")
            author: dict | None = item.get("author")

            if None in [name, path_word, author]:
                raise TypeError

            author_fmt: str = ""
            for z in author if author else {}:
                author_fmt += f"{f'{z.get("name")}'},"
            author_fmt = author_fmt[:-1]

            manga_list.append(path_word)  # type: ignore
            self.logger.info(f"[{i}] ({name}/{path_word}) {{{author_fmt}}}")

        index: int = 0
        max_index = len(manga_list)
        while True:
            self.logger.info(f"选择搜索结果(int<={max_index - 1})=")
            instr = input()
            try:
                index = int(instr, 10)
                if index < 0 and index >= max_index:
                    raise ValueError
            except Exception:
                self.logger.warn(f"输入的格式不正确或序号超出范围.")
                continue
            break

        return manga_list[index]

    def _InitInfo(self, pathword: str):
        results = self._ApiGet(
            f"https://api.{self.host}/api/v3/comic2/{pathword}",
            "",
        )

        comic: dict | None = results.get("comic")
        if comic is None:
            raise ValueError(f"JSON不存在路径[/results/comic]")

        manga = self.manga
        manga.alias = str(comic.get("alias"))
        manga.author = CopymangaItem.AuthorItem.FromMap(comic.get("author"))
        manga.cover = str(comic.get("cover"))
        manga.name = str(comic.get("name"))
        manga.path_word = str(comic.get("path_word"))
        status = comic.get("status")
        manga.status = str(status.get("display") if status else None)
        manga.uuid = str(comic.get("uuid"))

        groups: dict | None = results.get("groups")
        if groups is None:
            raise ValueError(f"JSON不存在路径[/results/groups]")
        for i in groups.keys():
            g_name: str | None = groups[i].get("name")
            g_path: str | None = groups[i].get("path_word")
            if g_path is None:
                continue
            group = CopymangaItem.GroupItem()
            group.name = str(g_name)
            group.path_word = str(g_path)
            self.manga.groups.append(group)

        return

    def ShowMangaInfo(self):
        manga = self.manga
        self.logger.info(f"漫画 {manga.path_word} 信息")
        self.logger.info(f"| 页面 -> https://{self.host}/comic/{manga.path_word} ")
        self.logger.info(f"| 名称 {manga.name} ")
        self.logger.info(f"| 作者 {manga.FormatAuthor()}")
        self.logger.info(f"| 标识 {manga.status} {manga.uuid}")
        self.logger.info(f"| 数据库 {manga.path_word}.db")
        for index, group in enumerate(manga.groups):
            self.logger.info(f"| 分组{index} {group.name}")
        return

    def _UpdatGroup(self, group: CopymangaItem.GroupItem, limit: int = 100) -> List[dict]:
        offset = 0
        chapters: List[dict] = []
        while True:
            results = self._ApiGet(
                f"https://api.{self.host}/api/v3/comic/{self.manga.path_word}/group/{group.path_word}/chapters"  #
                + f"?limit={limit}&offset={offset}&platform=3",
                "",
            )

            results_list = results.get("list")
            if results_list is None:
                raise ValueError(f"JSON不存在路径[/results/comic]")
            results_total = results.get("total")
            if results_total is None:
                raise ValueError(f"JSON不存在路径[/results/total]")

            chapters += results_list
            offset += limit

            if len(chapters) >= int(results_total):
                break

            continue

        return chapters

    def UpdateAllGroup(self):
        for group in self.manga.groups:
            results_list = self._UpdatGroup(group)
            group.chapters.clear()
            for chapter_json in results_list:
                chapter = CopymangaItem.ChapterItem()
                chapter.name = str(chapter_json.get("name"))
                chapter.uuid = str(chapter_json.get("uuid"))
                chapter.size = int(str(chapter_json.get("size")), 10)  # type: ignore
                chapter.index = int(str(chapter_json.get("index")), 10)  # type: ignore
                chapter.comic_id = str(chapter_json.get("comic_id"))
                chapter.comic_path_word = str(chapter_json.get("comic_path_word"))
                chapter.group_id = str(chapter_json.get("group_id"))
                chapter.group_path_word = str(chapter_json.get("group_path_word"))
                chapter.datetime_created = str(chapter_json.get("datetime_created"))
                chapter.prev_uuid = str(chapter_json.get("prev"))
                chapter.next_uuid = str(chapter_json.get("next"))
                group.chapters.append(chapter)
                continue
            continue
        return

    def ShowGroupInfo(self):
        manga_file_count = 0
        for group in self.manga.groups:
            self.logger.info(f"分组 {group.name} 共 {len(group.chapters)} 章节")
            group_file_count = 0
            for chapter in group.chapters:
                self.logger.info(f"| {str(chapter.index).zfill(3)}. {chapter.name}({chapter.size})")
                group_file_count += chapter.size
                continue
            manga_file_count += group_file_count
            self.logger.info(f"| 共 {group_file_count} 个文件")
            continue
        self.logger.info(f"所有分组共 {manga_file_count} 个文件")
        return

    def StartDownload(self):
        MultiCurl(
            self.database,
            "" if self.proxy is None else self.proxy["https"],
        ).Run()
        self.logger.info(f"下载完成")

    def _DownloadChapter(self, chapter: CopymangaItem.ChapterItem) -> int:
        results = self._ApiGet(
            f"https://api.{self.host}/api/v3/comic/{self.manga.path_word}/chapter2/{chapter.uuid}",
            "   ",
        )

        session = Session(self.database.engine)
        FileTableItem = MangaLocalDatabase.FileTableItem
        MetadataTableItem = MangaLocalDatabase.MetadataTableItem

        # 未在数据库中标记获取完成的章节

        results_chapter = results.get("chapter")
        if results_chapter is None:
            raise ValueError(f"JSON不存在路径[/results/chapter]")

        chapter_contents: List[dict] | None = results_chapter.get("contents")
        if chapter_contents is None:
            raise ValueError(f"JSON不存在路径[/results/chapter/contents]")
        chapter_words: List[int] | None = results_chapter.get("words")
        if chapter_words is None:
            raise ValueError(f"JSON不存在路径[/results/chapter/words]")

        for page, url in sorted(zip(chapter_words, chapter_contents)):
            url = str(url.get("url"))
            filetype = url[url.rfind(".") + 1 :]
            basepath = f"{self.manga.name}"
            filename = f"{chapter.name}-{str(page).zfill(3)}.{filetype}"

            items = session.scalars(
                select(
                    FileTableItem,
                ).where(FileTableItem.filename == filename),
            ).all()

            if len(items) == 1:
                item = items[0]
                item.url = url
                self.logger.info(f" ~ {str(page).zfill(3)} 更新({str(item.index).zfill(5)} -> {item.basepath}/{item.filename} -> {item.url})")
                continue

            if len(items) != 0:
                for item in items:
                    session.delete(item)
                    self.logger.info(f" - {str(page).zfill(3)} 移除({str(item.index).zfill(5)} -> {item.basepath}/{item.filename})")

            item = FileTableItem.Create(
                filename,
                basepath,
                url,
            )
            session.add(item)
            session.flush()

            self.logger.info(f" + {str(page).zfill(3)} 文件({str(item.index).zfill(5)} -> {item.basepath}/{item.filename} -> {item.url})")
            continue

        session.commit()

        self.logger.info(f" = 总文件数 {len(chapter_contents)}")

        self.StartDownload()

        # 获取完成下载的章节写入数据库标记

        session.add(
            MetadataTableItem.Create(
                "chapter",
                chapter.name,
                "",
                255,
            )
        )
        session.flush()
        session.commit()

        session.close()
        return len(chapter_contents)

    def DownloadAllChapters(self) -> None:
        total_files = 0

        session = Session(self.database.engine)
        MetadataTableItem = MangaLocalDatabase.MetadataTableItem

        for group in self.manga.groups:
            #
            self.logger.info(f"下载分组 {group.name} 中 {len(group.chapters)} 个章节")

            for index, chapter in enumerate(group.chapters):
                # 检查章节是否下载
                items = session.scalars(
                    select(
                        MetadataTableItem,
                    )
                    .where(MetadataTableItem.name == "chapter")
                    .where(MetadataTableItem.context == chapter.name),
                ).all()
                # 所有文件已经下载完成
                if len(items) == 1:
                    local_count = len(list(self.local_storage.rglob(f"{chapter.name}-*.webp")))
                    loss_count = chapter.size - local_count
                    if loss_count == 0:
                        self.logger.info(f"| [{str(index).zfill(4)}] 章节({chapter.name}) 已标记下载 本地文件数量({local_count})")
                    else:
                        self.logger.warn(f"| [{str(index).zfill(4)}] 章节({chapter.name}) 已标记下载 本地文件缺失({loss_count}/{local_count})")
                    continue
                # 数据库错误
                elif len(items) != 0:
                    self.logger.error(f"| [{str(index).zfill(4)}] 章节({chapter.name})拥有多个下载标记.")
                    raise ValueError(f"数据库章节标记重复")

                # 未下载
                self.logger.info(f"| [{str(index).zfill(4)}] 下载章节({chapter.name})")
                total_files += self._DownloadChapter(chapter)

                continue

            self.logger.info(f"| 新增下载任务 {total_files} 个文件")
            continue

        session.close()
        return

    def CheckLocalFile(self, mark_removed_file: bool = False):
        session = Session(self.database.engine)
        TableItem = MangaLocalDatabase.FileTableItem

        items: Sequence[MangaLocalDatabase.FileTableItem] = session.scalars(
            select(
                TableItem,
            ).where(TableItem.status == 255),
        ).all()

        self.logger.info(f"检查被记录的 {len(items)} 个本地文件")

        for i, item in enumerate(items):
            fullpath = Path(f"./dl.nosync/{item.basepath}/{item.filename}")
            if fullpath.exists():
                continue
            if mark_removed_file:
                self.logger.warn(f"文件丢失 {fullpath.as_posix()} 标记不下载")
                item.status = -1
                continue
            self.logger.warn(f"文件丢失 {fullpath.as_posix()} 将标记为未下载")
            item.status = 0
            continue

        session.commit()

        self.logger.info(f"本地文件检查完成")

        session.close()
        return

    def UpdateAndDownload(self):
        self.ShowMangaInfo()
        self.UpdateAllGroup()
        self.ShowGroupInfo()
        self.DownloadAllChapters()
        self.CheckLocalFile()


def Console():
    manga_list = [
        ("silentwitchchenmodemonvdemimi", "-Silent Witch-沉默的魔女的秘密"),
        ("yaoyeluying", "搖曳露營△"),
        ("zgmsbywt", "這個美術部有問題！"),
        ("yaowushaonvdeninancangtiansanzhilu", "藥屋少女的呢喃～貓貓的後宮解謎手冊～"),
        ("yaowushaonvdeninan", "葯屋少女的呢喃"),
        ("zaimowangchengshuowanan", "在魔王城說晚安"),
    ]

    def PrintList(manga_list: list):
        print()
        for i, data in enumerate(manga_list):
            path_word = data[0]
            manga_name = data[1]
            print(f"{str(i).zfill(2)}. [ {manga_name} / {path_word} ] ")

    PrintList(manga_list)

    max_index = len(manga_list)
    if max_index == 0:
        return

    while True:
        user_in = input("\n命令[索引值 update/show/check/download/mark]: ")
        cmd = user_in.split(" ")
        if len(cmd) != 2:
            PrintList(manga_list)
            continue

        index = 0
        index_str = cmd[0]
        do_str = cmd[1]

        select_all = True if index_str == "all" else False

        if select_all is False:
            try:
                index = int(index_str, 10)
                if index >= max_index:
                    print(f"索引值只能在[0-{max_index - 1}]范围内.")
            except Exception:
                print("索引值只能是[可选的整数]或[all].")
                continue

        if select_all:
            match do_str:
                case "update":
                    for pathname, _ in manga_list:
                        task = CopymangaTask(pathname)
                        task.UpdateAndDownload()
                case _:
                    print("不支持的操作.")
                    continue
            print("更新全部漫画完成.")
            continue

        task = CopymangaTask(manga_list[index][0])

        match do_str:
            case "update":
                task.UpdateAndDownload()
                continue

            case "show":
                task.ShowMangaInfo()
                task.UpdateAllGroup()
                task.ShowGroupInfo()
                continue

            case "check":
                task.CheckLocalFile()
                continue

            case "download":
                task.StartDownload()
                continue

            case "mark":
                task.CheckLocalFile(True)
                continue

            case _:
                print("不支持的操作.")
                continue

        continue

    return


if __name__ == "__main__":
    Console()
