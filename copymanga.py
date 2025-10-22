import re
import time
import datetime
import requests
import threading

from typing import Dict, List, Optional, Sequence, Tuple
from pathlib import Path
from pydantic import BaseModel


from sqlalchemy import select
from sqlalchemy.orm import Session

import database
import spdlogger

from uuid import UUID

logger = spdlogger.logger


class ApiRequsetLock:
    def __init__(self, num: int) -> None:
        self._queue: List[datetime.datetime] = []
        self._lock = threading.Lock()
        self._num = num

    def ReleaseTime(self):
        if len(self._queue) == 0:
            return 0
        return (self._queue[0] - datetime.datetime.now()).seconds

    def Reset(self):
        self._queue.clear()

    def Ready(self) -> bool:
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
        return f"{len(self._queue)}/{self._num}"


globle_copymanga_api_lock = ApiRequsetLock(15)


class ApiSearchComic(BaseModel):
    code: int
    message: str

    class Results(BaseModel):
        class ComicMetadata(BaseModel):
            name: str
            alias: str
            path_word: str
            cover: str

            class Author(BaseModel):
                name: str
                path_word: str

            author: List[Author]

        total: int
        limit: int
        offset: int
        list: List[ComicMetadata]

    results: Results


class ApiGetComic(BaseModel):
    code: int
    message: str

    class Results(BaseModel):
        class ComicInfo(BaseModel):
            uuid: UUID
            b_404: bool
            b_hidden: bool
            ban: int
            name: str
            alias: str
            path_word: str
            close_comment: bool
            close_roast: bool

            class FreeType(BaseModel):
                display: str
                value: int

            free_type: FreeType

            class Restrict(BaseModel):
                value: int
                display: str

            restrict: Restrict

            class Reclass(BaseModel):
                value: int
                display: str

            reclass: Reclass

            seo_baidu: str

            class Region(BaseModel):
                value: int
                display: str

            region: Region

            class Status(BaseModel):
                value: int
                display: str

            status: Status

            class Author(BaseModel):
                name: str
                path_word: str

            author: List[Author]

            class Theme(BaseModel):
                name: str
                path_word: str

            theme: List[Theme]

            brief: str
            datetime_updated: str
            cover: str

            class LastChapter(BaseModel):
                uuid: UUID
                name: str

            last_chapter: LastChapter
            popular: int

        is_banned: bool
        is_lock: bool
        is_login: bool
        is_mobile_bind: bool
        is_vip: bool
        comic: ComicInfo
        popular: int

        class GroupsMetadata(BaseModel):
            path_word: str
            count: int
            name: str

        groups: Dict[str, GroupsMetadata]

    results: Results


class ApiGetChapters(BaseModel):
    code: int
    message: str

    class Results(BaseModel):
        total: int
        limit: int
        offset: int

        class ChaptersMetadata(BaseModel):
            index: int
            uuid: UUID
            count: int
            ordered: int
            size: int
            name: str
            comic_id: UUID
            comic_path_word: str
            group_id: Optional[UUID]
            group_path_word: str
            type: int
            news: str
            datetime_created: str
            prev: Optional[UUID]
            next: Optional[UUID]

        list: List[ChaptersMetadata]

    results: Results


class ApiGetFiles(BaseModel):
    code: int
    message: str

    class Results(BaseModel):
        show_app: bool
        is_lock: bool
        is_login: bool
        is_mobile_bind: bool
        is_vip: bool

        class ComicMetadata(BaseModel):
            name: str
            uuid: UUID
            path_word: str

            class _Restrict(BaseModel):
                value: int
                display: str

            restrict: _Restrict

        comic: ComicMetadata

        class ChapterInfo(BaseModel):
            index: int
            uuid: UUID
            count: int
            ordered: int
            size: int
            name: str
            comic_id: UUID
            comic_path_word: str
            group_id: Optional[UUID]
            group_path_word: str
            type: int
            news: str
            datetime_created: str
            prev: Optional[UUID]
            next: Optional[UUID]

            class Content(BaseModel):
                url: str

            contents: List[Content]
            words: List[int]

            is_long: bool

        chapter: ChapterInfo
        is_banned: bool

    results: Results


class ComicFilePath:
    @staticmethod
    def BeginsAtDownloadDir(download: str, comic: str, group: str, index: int, chapter: str, page: str | int, ext: str):
        return f"{download}/{ComicFilePath.BeginsAtComicDir(comic, group, index, chapter, page, ext)}"

    @staticmethod
    def BeginsAtComicDir(comic: str, group: str, index: int, chapter: str, page: str | int, ext: str):
        return f"{comic}/{ComicFilePath.BeginsAtGroupDir(group, index, chapter, page, ext)}"

    @staticmethod
    def BeginsAtGroupDir(group: str, index: int, chapter: str, page: str | int, ext: str):
        if isinstance(page, int):
            page_str = f"{page:03d}"
        elif page == "*":
            page_str = page
        else:
            page_str = page.zfill(3)
        return f"{group}/{index:04d}.{chapter}-{page_str}.{ext}"

    @staticmethod
    def FromOrmGroupDir(file: database.TableFiles):
        return ComicFilePath.BeginsAtGroupDir(
            file.group,
            file.api_index,
            file.chapter,
            file.page,
            file.extension,
        )


def PrintWait(sec: int, gap: int, msg: str, print):
    loop = sec // gap
    end = sec % gap
    for i in range(loop):
        print(f"{msg} 等待 {sec - i * gap} 秒")
        time.sleep(gap)
    print(f"{msg} 等待 {end} 秒")
    time.sleep(end)
    return


class CopymangaObject:
    def __init__(
        self,
        download_root: Path,
        database_root: Path,
        pathword: Optional[str] = None,
        keyword: Optional[str] = None,
        proxy: Optional[str] = None,
    ) -> None:
        self.logger = logger.ObjLogger(self)

        self.host: str = "mangacopy.com"
        self.proxy: Optional[dict] = None
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

        if proxy is not None:
            self.logger.info(f"使用系统代理 {proxy}")
            self.proxy = {"https": f"http://{proxy}"}

        self.lock = globle_copymanga_api_lock

        # 如果用 关键词 为参数
        if pathword is None and isinstance(keyword, str):
            init_pathword = self.Search(keyword)
            if init_pathword is None:
                self.logger.warn(f"未搜索到任何内容")
                raise ValueError("无法从关键词初始化对象")

        # 如果用 漫画ID 为参数
        elif keyword is None and isinstance(pathword, str):
            init_pathword = pathword

        # 构造参数不正确
        else:
            self.logger.error(f"初始化参数错误 pathword=[{pathword}] keyword=[{keyword}]")
            raise ValueError("对象初始化参数错误")

        # 获取 漫画信息
        data = self.GetInfo(init_pathword)
        if data is None:
            self.logger.error(f"输入的漫画(id={pathword})不存在")
            raise ValueError("无法从关路径词初始化对象")

        self.data = data

        self.groups: Dict[str, ApiGetComic.Results.GroupsMetadata] = self.data.groups
        self.comic: ApiGetComic.Results.ComicInfo = self.data.comic

        # 初始化 漫画本地数据库和目录
        self.download_folder = download_root / Path(self.data.comic.name)
        self._db_file = database_root / Path(f"{self.data.comic.path_word}.db")
        self.database = database.SqliteClient(self._db_file)
        self._CheckBaseMetadata()

        return

    def Get(self, url, msg: str = "") -> dict:
        while not self.lock.Ready():
            self.logger.debug(f"等待API请求数 {self.lock.ReleaseTime()}s")
            time.sleep(10)

        err = 0

        while True:
            try:
                self.lock.CountAdd()
                self.logger.debug(f"{msg}请求 {url} 请求数({self.lock})")
                ret = requests.get(url, headers=self.header, proxies=self.proxy)

            except Exception as e:
                err += 1
                self.logger.warn(f"{msg}重试第 {err} 次")
                self.logger.warn(f"{msg}| {e}")
                time.sleep(1)
                continue

            if err > 4:
                self.logger.error(f"{msg}无法请求 {url}")
                raise ConnectionError

            if ret.status_code < 200 or ret.status_code > 299:
                self.logger.error(f"{msg}请求失败 HTTP{ret.status_code}")
                raise ValueError

            throttled_sec = self.Throttled(ret.json())

            if throttled_sec is None:
                break

            throttled_sec += 5

            self.logger.warn(f"超出API请求次数 等待 {throttled_sec} 秒")
            PrintWait(throttled_sec, 10, "", logger.debug)
            self.lock.Reset()
            continue

        results = self.GetResults(ret.json())

        return results

    def Throttled(self, j: dict):
        code = j.get("code")
        if code is None:
            raise ValueError(f"不支持的消息: 无[/code] {j}")
        if code != 210:
            return None
        message = j.get("message", "")
        if message is None:
            return None
        if not ("throttled" in message and "seconds" in message):
            return None
        m = re.findall(r"\d+", message)
        if len(m) != 1:
            return None
        return int(m[0], 10)

    def GetResults(self, j: dict) -> dict:
        json_code: int | None = j.get("code")
        json_results: dict | None = j.get("results")
        if json_code is None or (isinstance(json_code, int) and json_code != 200):
            raise ValueError(f"API返回状态 {json_code} {j}")
        if json_results is None:
            raise ValueError(f"JSON不存在路径[/results]")
        return json_results

    @staticmethod
    def SetMetadata(manga_db: database.SqliteClient, tag: str, context: str, status: int):
        Table = database.TableMetadata
        with Session(manga_db.engine) as session:
            item = Table.Create(tag, context, status)
            session.add(item)
            session.flush()
            session.commit()

        return

    @staticmethod
    def GetMetadata(manga_db: database.SqliteClient, tag: str):
        r: List[Tuple[str, str, int]] = []
        Table = database.TableMetadata
        with Session(manga_db.engine) as session:
            items = session.scalars(
                select(
                    Table,
                ).where(Table.tag == tag),
            ).all()
            for item in items:
                r.append((item.tag, item.context, item.status))
                continue
            pass
        return r

    def _CheckBaseMetadata(self):
        check_name = self.GetMetadata(self.database, "__name__")
        if len(check_name) == 0:
            self.SetMetadata(self.database, "__name__", self.data.comic.name, 0)
        elif len(check_name) != 1:
            raise ValueError(f"数据库错误 漫画被记录多个名称")

        check_pathword = self.GetMetadata(self.database, "__pathword__")
        if len(check_pathword) == 0:
            self.SetMetadata(self.database, "__pathword__", self.data.comic.path_word, 0)
        elif len(check_pathword) != 1:
            raise ValueError(f"数据库错误 漫画被记录多个ID")

        return

    def Search(self, kw: str) -> str | None:
        results = ApiSearchComic.Results(
            **self.Get(
                f"https://api.{self.host}/api/v3/search/comic?format=json&platform=3&q={kw}&limit=10&offset=0",
                "",
            )
        )

        if len(results.list) == 0:
            return None

        data_list: List[str] = []
        for i, item in enumerate(results.list):
            name = item.name
            path_word = item.path_word
            author = item.author

            author_fmt: str = ""
            for z in author:
                author_fmt += f"{z.name}, "
            if len(author_fmt):
                author_fmt = author_fmt[:-2]
            data_list.append(path_word)
            self.logger.info(f"[{i}] ({name}/{path_word}) {{ {author_fmt} }}")

        index: int = 0
        max_index = len(data_list)
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

        return data_list[index]

    def GetInfo(self, pathword: str) -> Optional[ApiGetComic.Results]:
        try:
            results = ApiGetComic.Results(
                **self.Get(
                    f"https://api.{self.host}/api/v3/comic2/{pathword}",
                    "",
                )
            )
        except Exception as e:
            self.logger.error(f"{e}")
            return None
        return results

    def ShowMetadate(self) -> None:
        groups = self.groups
        comic = self.comic
        self.logger.info(f"漫画 {comic.path_word} 信息")
        self.logger.info(f"| 页面 [ https://{self.host}/comic/{comic.path_word} ]")
        self.logger.info(f"| 名称 [ {comic.name} ]")
        author = str()
        for item in comic.author:
            author += item.name + ", "
        if len(author):
            author = author[:-2]
        self.logger.info(f"| 作者 [ {author} ]")
        self.logger.info(f"| 标识 [ {comic.status} {comic.uuid} ]")
        self.logger.info(f"| 数据 [ {self.database.engine} ]")
        for index, group in enumerate(groups.values()):
            self.logger.info(f"| 分组{index} [ {group.name} {group.count} {group.path_word} ]")
        return

    def GetFiles(self, chapter: ApiGetChapters.Results.ChaptersMetadata) -> Dict[int, str] | None:
        comic = self.comic

        results = ApiGetFiles.Results(
            **self.Get(
                f"https://api.{self.host}/api/v3/comic/{comic.path_word}/chapter2/{chapter.uuid}",
                "|   ",
            )
        )

        words = results.chapter.words
        contents = results.chapter.contents

        if not (len(words) == len(contents) == chapter.size):
            self.logger.error(f"数量不一致")
            return None

        files: Dict[int, str] = {}

        for page, content in sorted(zip(words, contents)):
            files[page] = content.url

        return files

    def GetChapters(self, group: ApiGetComic.Results.GroupsMetadata) -> List[ApiGetChapters.Results.ChaptersMetadata]:
        offset = 0
        limit = 100
        chapters: List[ApiGetChapters.Results.ChaptersMetadata] = []
        while True:
            results = ApiGetChapters.Results(
                **self.Get(
                    f"https://api.{self.host}/api/v3/comic/{self.data.comic.path_word}/group/{group.path_word}/chapters"  #
                    + f"?limit={limit}&offset={offset}&platform=3",
                    "| ",
                )
            )
            chapters += results.list
            offset += limit
            if len(chapters) >= int(results.total):
                break
            continue
        return chapters

    def UpdateGroup(self, group: ApiGetComic.Results.GroupsMetadata, not_files=False) -> int:
        comic = self.comic

        # ================================================================================================================================

        def CheckChapterCompleted(
            group: ApiGetComic.Results.GroupsMetadata,
            chapter: ApiGetChapters.Results.ChaptersMetadata,
        ) -> bool:
            TableChapters = database.TableChapters
            with Session(self.database.engine) as session:
                items = session.scalars(
                    select(
                        TableChapters,
                    ).where(TableChapters.uuid == chapter.uuid)
                ).all()

                # 章节 已完成
                if len(items) == 1:
                    local_files = list(
                        self.download_folder.glob(
                            ComicFilePath.BeginsAtGroupDir(group.name, chapter.index, chapter.name, "*", "*"),
                        )
                    )

                    # 检查 本地文件数量
                    local_cont = len(local_files)
                    loss_count = chapter.size - local_cont

                    if loss_count == 0:
                        self.logger.info(f"| 文件完整 {chapter.size:03d} [{items[0].index:03d}] {chapter.name}")
                    else:
                        self.logger.info(f"| 文件缺少 {chapter.size - local_cont:03d} 个 [{items[0].index:03d}] {chapter.name}")

                    return True

                # 章节 重复记录
                elif len(items) != 0:
                    for item in items:
                        session.delete(item)
                        self.logger.warn(f"| [{item.index:03d}]  {chapter.name} 章节重复记录 已被移除")
                    return False

                # 章节 未被记录
                pass

            return False

        # ================================================================================================================================

        def InsertFile(
            session: Session,
            group: ApiGetComic.Results.GroupsMetadata,
            chapter: ApiGetChapters.Results.ChaptersMetadata,
            page: int,
            url: str,
        ) -> int:
            TableFile = database.TableFiles

            extension = url[url.rfind(".") + 1 :]
            fullpath = ComicFilePath.BeginsAtGroupDir(
                group.name,
                chapter.index,
                chapter.name,
                page,
                extension,
            )

            items = session.scalars(
                select(TableFile)
                .where(TableFile.group == group.name)
                .where(TableFile.chapter == chapter.name)
                .where(TableFile.page == page)
                .where(TableFile.extension == extension),
            ).all()

            # 文件 更新URL
            if len(items) == 1:
                item = items[0]
                item.dl_url = url
                session.commit()
                self.logger.debug(f"|   更新文件 {items[0].index:04d} {fullpath} {item.dl_url}")
                return item.index

            # 文件 重复任务
            elif len(items) != 0:
                for item in items:
                    session.delete(item)
                    self.logger.warn(f"|   移除文件 {item.index:04d} {fullpath} {item.dl_url}")
                pass

            # 文件 无任务
            item = TableFile.Create(
                api_index=chapter.index,
                group=group.name,
                chapter=chapter.name,
                page=page,
                extension=extension,
                dl_path=comic.name,
                dl_url=url,
                dl_skip=False,
                dl_status=database.FileDlStatus.NewFile,
                status=0,
            )
            session.add(item)
            session.flush()
            session.commit()

            self.logger.info(f"|   记录文件 {item.index:04d} + {fullpath}")
            return item.index

        # ================================================================================================================================

        def InsertFiles(
            group: ApiGetComic.Results.GroupsMetadata,
            chapter: ApiGetChapters.Results.ChaptersMetadata,
            files: Dict[int, str],
        ) -> int:
            TableChapters = database.TableChapters

            with Session(self.database.engine) as session:
                # 记录文件
                for page in files.keys():
                    url = files[page]
                    InsertFile(session, group, chapter, page, url)
                    continue
                # 标记章节完成
                item = TableChapters.Create(
                    api_index=chapter.index,
                    group=group.name,
                    name=chapter.name,
                    size=chapter.size,
                    uuid=chapter.uuid,
                    status=0,
                )
                session.add(item)
                session.flush()
                session.commit()

                self.logger.info(f"|   完成章节 {item.index:04d}")

            return len(files)

        # ================================================================================================================================

        def PrintChapters(chapters: List[ApiGetChapters.Results.ChaptersMetadata]):
            for chapter in chapters:
                self.logger.info(f"| {chapter.index:04d}. {chapter.name}({chapter.size})")

        # ================================================================================================================================
        def Update() -> int:
            total_files = 0
            total_update = 0

            self.logger.info(f"获取分组 [ {group.name} ] 共 {group.count} 个章节")
            chapters = self.GetChapters(group)

            # 仅显示在线章节目录
            if not_files:
                PrintChapters(chapters)
                return 0

            for chapter in chapters:
                # 检查章节已完成
                if CheckChapterCompleted(group, chapter):
                    continue

                # 获取章节文件列表
                self.logger.info(f"| + 章节({chapter.name})")
                files = self.GetFiles(chapter)
                if files is None:
                    self.logger.error(f"|   获取文件失败")
                    continue
                files_count = InsertFiles(group, chapter, files)

                # 更新计数
                total_files += files_count
                total_update += 1
                continue

            if total_files == 0:
                self.logger.debug(f"| 本地记录已是最新")
            else:
                self.logger.info(f"| 记录 {total_update} 个章节 {total_files} 个文件")

            return total_update

        return Update()

    def UpdateAll(self, not_files=False):
        files_count = 0
        for group in self.groups.values():
            files_count += self.UpdateGroup(group, not_files)
            continue
        if not_files is False:
            self.logger.info(f"更新完成 共记录 {files_count} 个文件")
        else:
            self.logger.info(f"获取完成")
        return

    def DetectFiles(self):
        Table = database.TableFiles
        with Session(self.database.engine) as session:
            items = session.scalars(
                select(Table),
            ).all()

            self.logger.info(f"检查所有 {len(items)} 个文件的完成状态")

            for item in items:
                filepath = self.download_folder / ComicFilePath.BeginsAtGroupDir(
                    item.group,
                    item.index,
                    item.chapter,
                    item.page,
                    item.extension,
                )

                if not filepath.exists():
                    continue

                self.logger.info(f'| 标记 {item.index:04d} "{filepath.as_posix()}" 为已下载')
                item.dl_status = database.FileDlStatus.Completed
                session.commit()
                continue
            pass
        self.logger.info(f"文件检查完成")
        return

    def CheckFiles(self, mark_removed_file: bool = False):
        Table = database.TableFiles

        with Session(self.database.engine) as session:
            # ================================================================================================================================

            items = session.scalars(
                select(Table)
                .where(Table.dl_skip == False)  # noqa: E712
                .where(Table.dl_status == database.FileDlStatus.Completed),
            ).all()

            self.logger.info(f"检查已完成的 {len(items)} 个文件")

            for item in items:
                filepath = self.download_folder / ComicFilePath.FromOrmGroupDir(item)

                if filepath.exists():
                    continue

                if mark_removed_file:
                    self.logger.warn(f'| 文件丢失 "{filepath.as_posix()}" 将标记为跳过下载')
                    item.dl_skip = True
                    session.commit()
                    continue

                self.logger.warn(f'| 文件丢失 "{filepath.as_posix()}" 将标记为未下载')
                item.dl_status = 0
                session.commit()
                continue

            # ================================================================================================================================

            items = session.scalars(
                select(Table)
                .where(Table.dl_skip == False)  # noqa: E712
                .where(Table.dl_status == database.FileDlStatus.Active),
            ).all()

            self.logger.info(f"未完成下载共 {len(items)} 个文件")

            # ================================================================================================================================

            items = session.scalars(
                select(Table)
                .where(Table.dl_skip == False)  # noqa: E712
                .where(Table.dl_status == database.FileDlStatus.NewFile),
            ).all()

            self.logger.info(f"未开始共 {len(items)} 个文件")

            # ================================================================================================================================

        self.logger.info(f"文件检查完成")
        return


def module_test():
    from main import win32proxy
    from main import DB_ROOT, DOWNLOAD_ROOT

    # url = f"https://api.mangacopy.com/api/v3/search/comic?format=json&platform=3&q={"沉默魔女"}&limit=10&offset=0"
    # url = f"https://api.mangacopy.com/api/v3/comic2/{'silentwitchchenmodemonvdemimi'}"
    # url = f"https://api.mangacopy.com/api/v3/comic/{'silentwitchchenmodemonvdemimi'}/group/{'default'}/chapters?limit={10}&offset={0}&platform=3"
    # url = f"https://api.mangacopy.com/api/v3/comic/{'silentwitchchenmodemonvdemimi'}/chapter2/{"2457082c-e25d-11eb-8bdc-00163e0ca5bd"}"

    # ret = requests.get(
    #     url,
    #     headers={
    #         "User-Agent": "duoTuoCartoon/3.2.4 (iPhone; iOS 18.0.1; Scale/3.00) iDOKit/1.0.0 RSSX/1.0.0",
    #         "version": "2025.10.12",
    #         "region": "0",
    #         "webp": "1",
    #         "platform": "1",
    #         "referer": "https://www.copymanga.com/",
    #         "use_oversea_cdn": "1",
    #         "use_webp": "1",
    #     },
    # )

    # print(ret.status_code)
    # print()
    # print(ret.json())

    # print("\n")
    # print("测试 使用关键词搜索")
    # pathword = CopymangaObject(database_root=DB_ROOT, keyword="沉默魔女", proxy=win32proxy().get_proxy()).comic.path_word

    # print("\n")
    # print("测试 使用漫画ID初始化")
    # obj = CopymangaObject(database_root=DB_ROOT, pathword="silentwitchchenmodemonvdemimi", proxy=win32proxy().get_proxy())
    # obj.ShowMetadate()
    # obj.UpdateAll(not_files=True)

    print("\n")
    print("测试 更新漫画所有分组")
    obj = CopymangaObject(download_root=DOWNLOAD_ROOT, database_root=DB_ROOT, pathword="silentwitchchenmodemonvdemimi", proxy=win32proxy().get_proxy())
    obj.ShowMetadate()
    obj.UpdateAll()
    num = 0
    while True:
        print(num)

        obj.Get(f"https://api.{obj.host}/api/v3/search/comic?format=json&platform=3&q=沉默魔女&limit=10&offset=0", "")

        num += 1


if __name__ == "__main__":
    module_test()
