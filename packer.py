import datetime
import os
from pathlib import Path
from pprint import pprint
from typing import Dict, List, Tuple
from copymanga import CopymangaObject
from database import ComicDatabase
import database
from main import CBZ_ROOT, DB_ROOT, DOWNLOAD_ROOT, FILE_PREFIX, FILE_SUFFIX
from spdlogger import logger
import subprocess
from configparser import ConfigParser
import unicodedata
import zipfile


def isInvalidPath(s: str):
    for ch in s:
        if ch in r'[\:*?"<>|]':
            return True
        continue
    return False


class StringView:
    def __init__(self, s: str) -> None:
        self.s = s
        self.i = 0

    def __str__(self) -> str:
        base = f'"{self.s}"\n '
        if self.IndexOverflow():
            index = len(self.s) - 1
        else:
            index = self.i

        for ch in self.s[0 : self.i]:
            width = self.GetCharSize(ch)
            base += "-" * width

        return base + "↑" * self.GetCharSize(self.s[index]) + f" [{index}]"

    @staticmethod
    def GetCharSize(ch: str) -> int:
        match unicodedata.east_asian_width(ch):
            case "F":
                return 2
            case "H":
                return 1
            case "W":
                return 2
            case "Na":
                return 1
            case "A":
                return 1
            case "N":
                return 1

    def Next(self, i: int = 1):
        self.i += i

    def IndexOverflow(self, offset: int = 0):
        if self.i + offset < 0:
            return True
        if self.i + offset >= len(self.s):
            return True
        return False

    def GetChar(self):
        if self.IndexOverflow():
            return None
        c = self.s[self.i]
        return c

    def GetStr(self, size: int):
        cut_min = int(0)
        cut_max = len(self.s)

        i1 = self.i
        if i1 > cut_max:
            i1 = cut_max
        elif i1 < cut_min:
            i1 = cut_min

        i2 = self.i + size
        if i2 > cut_max:
            i2 = cut_max
        elif i2 < cut_min:
            i2 = cut_min

        if size < cut_min:
            s = self.s[i2:i1]
        else:
            s = self.s[i1:i2]

        if len(s) == 0:
            return None
        return s


class PackageChapter:
    def __init__(self, group: str, name: str) -> None:
        self.group = group
        self.name = name

        self.index: int = -1
        self.number: float | None = None

        buf: str = ""
        start = False
        for ch in name:
            if ch not in r"0123456789.":
                if start:
                    break
                continue
            start = True
            buf += ch
        try:
            self.number = float(buf)
        except Exception:
            self.number = None

        return

    def __str__(self) -> str:
        return f"<{PackageChapter.__name__} identifier={self.GetIdentifier()} num={self.number} />"

    def __repr__(self) -> str:
        return self.__str__()

    @staticmethod
    def FromIdentifier(identifier: str):
        split = identifier.split("/")
        if len(split) != 2:
            raise ValueError(f"章节标识 {identifier} 格式不正确")
        return PackageChapter(split[0], split[1])

    def GetGlob(self, prefix: str, suffix: str):
        return f"{self.group}/{prefix}{self.name}{suffix}"

    def GetFiles(self, comic_root: Path, prefix: str, suffix: str):
        return list(comic_root.glob(self.GetGlob(prefix, suffix)))

    def GetIdentifier(self):
        if self.group is None:
            return self.name
        return f"{self.group}/{self.name}"

    @staticmethod
    def Sort(chapters: "List[PackageChapter]"):
        sort_ref: List[float] = []
        sort_list: List[PackageChapter] = []
        notsort_list: List[PackageChapter] = []
        for chapter in chapters:
            if chapter.number is None:
                notsort_list.append(chapter)
                continue
            sort_ref.append(chapter.number)
            sort_list.append(chapter)
            continue
        return [
            item
            for ref, index, item in sorted(
                zip(
                    sort_ref,
                    range(len(sort_list)),
                    sort_list,
                )
            )
        ], notsort_list


class ComicPackage:
    ST_STOP = -1
    ST_FIND_START_SQ = 1
    ST_FIND_VALUE_NO_SPACE = 2
    ST_FIND_VALUE_WITH_SPACE = 3

    def __init__(self, comic_dir: Path, output_dir: Path, comic_name: str, cbz_name: str, glob_prefix: str, glob_suffix: str) -> None:
        self.comic_dir: Path = comic_dir
        self.output_dir = output_dir
        self.skip_output = False
        self.comic_name: str = comic_name
        self.cbz_name: str = cbz_name
        self.glob_prefix = glob_prefix
        self.glob_suffix = glob_suffix
        self.groups: Dict[str, Dict[str, PackageChapter]] = {}

    @staticmethod
    def FromParse(comic_dir: Path, output_dir: Path, comic_name: str, cbz_name: str, parse_text: str, glob_prefix: str, glob_suffix: str):
        cbz = ComicPackage(comic_dir, output_dir, comic_name, cbz_name, glob_prefix, glob_suffix)

        cbz.ParseConfig(f" {parse_text} ")
        return cbz

    def FormatChapterAndCount(self):
        chapters_str: str = " "
        for group in self.groups.values():
            for chapter in group.values():
                file_count = len(chapter.GetFiles(self.comic_dir, self.glob_prefix, self.glob_suffix))
                chapters_str += f"{chapter.GetIdentifier()}:{file_count} "
                continue
            continue
        return chapters_str

    def __str__(self) -> str:
        return f'<{ComicPackage.__name__} name="{self.GetFileName().as_posix()}" config={self.FormatConfig()}>'

    def __repr__(self) -> str:
        return self.__str__()

    def GetFiles(self):
        files: List[Path] = []
        for group in self.groups.values():
            for chapter in group.values():
                files += chapter.GetFiles(self.comic_dir, self.glob_prefix, self.glob_suffix)
                continue
            continue
        return files

    def GetChapterFiles(self):
        files: List[List[Path]] = []
        for group in self.groups.values():
            for chapter in group.values():
                files.append(chapter.GetFiles(self.comic_dir, self.glob_prefix, self.glob_suffix))
                continue
            continue
        return files

    def GetChapter(self, group: str, identifier: str):
        g = self.groups.get(group)
        if g is None:
            return None
        return g.get(identifier)

    def GetNumber(self):
        sort = self.GetNumberAll()
        if sort is None:
            return None
        return sort[0]

    def GetNumberAll(self):
        if len(self.groups.keys()) != 1:
            return None
        group = list(self.groups.values())[0]
        sort, _ = PackageChapter.Sort(list(group.values()))
        nums: List[float] = []
        for chapter in sort:
            if chapter.number is None:
                continue
            nums.append(chapter.number)
        if len(nums) == 0:
            return None
        return nums

    def AutoSetName(self):
        group = list(self.groups.keys())

        def ExportGroupDesc(group: Dict[str, PackageChapter]):
            chapters = list(group.values())
            if len(chapters) == 0:
                return ""

            if len(chapters) == 1:
                return f"{chapters[0].group}({chapters[0].name})"

            sort_chapters, nosort = PackageChapter.Sort(chapters)

            if len(sort_chapters) == 0:
                raise IndexError

            first = sort_chapters[0]
            last = sort_chapters[-1]

            name = f"{first.group}({first.name}-{last.name})"

            for chapter in nosort:
                name = f"{name[:-1]}-{chapter.name})"

            return name

        name: str = ""
        for group in self.groups.keys():
            name += ExportGroupDesc(self.groups[group])

        self.cbz_name = name
        return

    def GetFileName(self) -> Path:
        return Path(f"{self.comic_name} {self.cbz_name}.cbz")

    def ParseConfig(self, format_str: str):
        # CBZ NAME = [ 格式 格式 ]
        # 单章格式 第01话
        # 连续格式 ......
        # 空格格式 "第01 话"

        view = StringView(format_str)

        identifier_list: List[str] = []
        buf: str = ""
        status: int = 0

        skip: bool = False
        step: int = self.ST_FIND_START_SQ

        while True:
            # 循环打断
            if self.ST_STOP == step:
                break
            ch = view.GetChar()
            if ch is None and len(buf) != 0:
                raise SyntaxError(f'语法错误 \n"{view.s}" "{"-" * (view.i - len(buf))}{"↑" * len(buf)}" 意外结尾 \n')
            if ch is None:
                break

            # 任意字符后第一个'[ '后 开始解析
            if self.ST_FIND_START_SQ == step:
                # 仅允许跳过空格
                if ch == " ":
                    pass
                # 寻找第一个"#"标积文件跳过导出
                elif ch == "#":
                    skip = True
                # 寻找第一个"["开始
                elif ch == "[":
                    check = view.GetStr(2)
                    if check is None or len(check) != 2:
                        raise SyntaxError(f"语法错误 \n{view} 语句不应就此结束\n")
                    # 寻找第二个" "结束
                    elif check[1] != " ":
                        raise SyntaxError(f"语法错误 \n{view} 字符应该是空格\n")
                    # 出现空格 从空格开始尝试捕获
                    status = 0
                    step = self.ST_FIND_VALUE_NO_SPACE
                # else:
                #     raise SyntaxError(f"语法错误 \n{view} 此处应该是' '或'#'或'['\n")
                # 下一字符
                view.Next(1)
                continue

            # 任意(除空格)字符 开始捕获
            elif self.ST_FIND_VALUE_NO_SPACE == step:
                # 未开始时
                if status == 0:
                    if ch != " ":
                        raise SyntaxError(f"语法错误 \n{view} 应该是空格\n")
                    # 出现第一个空格
                    status = 4
                    continue

                # 出现至少一个空格 才能开始捕获
                elif status == 4:
                    # 出现空格 保持字符 检查解析完成
                    if ch == " ":
                        status = 3
                        continue
                    # 出现双引号 开始捕获
                    elif ch == '"':
                        status = 0
                        step = self.ST_FIND_VALUE_WITH_SPACE
                    # 出现任何非空格字符 开始捕获
                    else:
                        buf += ch
                        status = 1
                    pass

                # 出现空格后
                elif status == 3:
                    # 检查' ]'完成解析
                    check = view.GetStr(2)
                    if check is None or len(check) != 2:
                        raise SyntaxError(f"语法错误 \n{view} 语句不应就此结束\n")
                    if check[1] == "]":
                        step = self.ST_STOP
                        continue
                    # 继续尝试开始捕获
                    status = 4

                # 开始捕获
                elif status == 1:
                    # 出现空格结束 保持字符 捕获下一个
                    if ch == " ":
                        identifier_list.append(buf)
                        buf = ""
                        status = 0
                        step = self.ST_FIND_VALUE_NO_SPACE
                        continue
                    # 捕获其他字符
                    else:
                        buf += ch
                    pass

                # 下一字符
                view.Next(1)
                continue

            # 任意(除双引号外)字符 开始捕获
            elif self.ST_FIND_VALUE_WITH_SPACE == step:
                # 持续捕获
                if status == 0:
                    buf += ch
                    # 出现双引号 保持字符 检查捕获结束
                    if ch == '"':
                        status = 1
                        continue

                # 出现双引号后
                elif status == 1:
                    # 检查'" '结束捕获
                    check = view.GetStr(2)
                    if check is None or len(check) != 2:
                        raise SyntaxError(f"语法错误 \n{view} 语句不应就此结束\n")
                    # 出现空格 从空格开始尝试捕获
                    if check[1] == " ":
                        identifier_list.append(buf[:-1])
                        buf = ""
                        status = 0
                        step = self.ST_FIND_VALUE_NO_SPACE
                        # 当前索引为"符号
                        view.Next(1)
                        continue
                    else:
                        # 继续捕获
                        status = 0

                # 下一字符
                view.Next(1)
                continue

            pass

        self.groups.clear()

        if skip:
            self.skip_output = True

        for identifier in identifier_list:
            if isInvalidPath(identifier):
                raise ValueError(f"标识 {[identifier]} 中包含文件系统路径非法字符")
            chapter = PackageChapter.FromIdentifier(identifier)
            if self.groups.get(chapter.group) is None:
                self.groups[chapter.group] = {}
            self.groups[chapter.group][chapter.name] = chapter
            continue

        return

    def FormatConfig(self):
        buf: str = "# " if self.skip_output else ""
        buf += "[ "
        for group in self.groups.keys():
            for chapter in self.groups[group].values():
                identifier = chapter.GetIdentifier()
                if '"' in identifier:
                    buf += f'"{identifier}" '
                    continue
                buf += f"{identifier} "
                continue
            continue
        buf += "]"
        return buf


class FilePacker:
    _INI_CONFIG = "Config"
    _INI_CONFIG_CBZ_PREFIX = "CBZ_PREFIX"
    _INI_CONFIG_GLOB_PREFIX = ["GLOB_PREFIX", FILE_PREFIX]
    _INI_CONFIG_GLOB_SUFFIX = ["GLOB_SUFFIX", FILE_SUFFIX]
    _INI_CBZ_FILES = "Cbz"
    _INI_CBZ_EXAMPLE = {
        # "语法示例CBZ定义格式1": "CBZ文件名 = [ 第0话 第1话 第2话 ]              // 开头[后一个字符，结尾]前一个字符，是必须是空格",
        # "语法示例CBZ跳过导出1": "CBZ文件名 = # [ 第0话 第1话 第2话 ]            // 在[之前任意位置增加#符号，可定义跳过文件导出",
        # "语法示例CBZ章节格式1": 'CBZ文件名 = [ 第0话 "第1 话" 第2话 ]           // 使用"包括章节名，结束的"后一个字符必须是空格，才会完成解析',
        # "语法示例CBZ章节格式2": "CBZ文件名 = [ 第0话 ..... 第2话 ]              // 使用五个点以进行，连续匹配到下一个章节",
        # "语法示例CBZ章节格式3": "CBZ文件名 = [ 第0话 第1话 ..... ]              // 在结尾使用连续匹配，会连续匹配到最后的章节",
    }

    def __init__(
        self,
        output_root: Path,
        download_root: Path,
        database_root: Path,
        pathword: str,
    ) -> None:
        self.logger = logger.ObjLogger(self)

        self.cbz_tasks: List[ComicPackage] = []

        self.download_root = download_root
        self.database_root: Path = database_root

        self.comic_db: ComicDatabase = database.ComicDatabase(self.database_root / Path(f"{pathword}.db"))

        self.comic_name = self.comic_db.attribute.GetName()
        self.comic_pathword = self.comic_db.attribute.GetPathword()

        self.exist_groups: Dict[str, Dict[str, PackageChapter]] = {}

        self.comic_dir = self.download_root / self.comic_name
        self.output_dir = output_root / self.comic_name

        if self.output_dir.is_file():
            raise ValueError(f'目录异常 导出路径被文件占用 "{self.output_dir.as_posix()}" 是一个文件')

        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.glob_prefix = FILE_PREFIX
        self.glob_suffix = FILE_SUFFIX
        self.cbz_prefix = str()

        self.conf_file = self.database_root / Path(f"{pathword}.ini")
        self.conf = self._LoadConfig()

        self.SaveConfig()
        return

    def _LoadCbzSection(self, conf: ConfigParser):
        if not conf.has_section(self._INI_CBZ_FILES):
            return

        cbz_files = conf.options(self._INI_CBZ_FILES)
        self.cbz_tasks.clear()
        self.exist_groups.clear()

        for cbz_name in cbz_files:
            #
            cbz = ComicPackage.FromParse(
                self.comic_dir,
                self.output_dir,
                self.cbz_prefix,
                cbz_name,
                conf.get(self._INI_CBZ_FILES, cbz_name),
                self.glob_prefix,
                self.glob_suffix,
            )

            self.cbz_tasks.append(cbz)

            for group_name in cbz.groups.keys():
                chapters = cbz.groups[group_name]
                if self.exist_groups.get(group_name) is None:
                    self.exist_groups[group_name] = {}
                group = self.exist_groups[group_name]
                exist_chapter = list(group.keys())

                for chapter_name in chapters.keys():
                    chapter = chapters[chapter_name]
                    if chapter_name in exist_chapter:
                        raise ValueError(f"章节 {group_name}/{chapter_name} 被多个CBZ引用")
                    group[chapter_name] = chapter
                    continue

                # for group
                continue

            # for cbz
            continue

        return

    def _LoadConfig(self) -> ConfigParser:
        conf = ConfigParser(allow_no_value=True)
        if not self.conf_file.exists():
            self.logger.debug(f'配置不存在 创建默认配置 "{self.conf_file.as_posix()}"')
            conf.add_section(self._INI_CONFIG)
            conf.set(self._INI_CONFIG, self._INI_CONFIG_CBZ_PREFIX, self.comic_dir.name)
            conf.set(self._INI_CONFIG, self._INI_CONFIG_GLOB_PREFIX[0], self._INI_CONFIG_GLOB_PREFIX[1])
            conf.set(self._INI_CONFIG, self._INI_CONFIG_GLOB_SUFFIX[0], self._INI_CONFIG_GLOB_SUFFIX[1])
            for key in self._INI_CBZ_EXAMPLE.keys():
                conf.set(self._INI_CONFIG, key, self._INI_CBZ_EXAMPLE[key])
            conf.add_section(self._INI_CBZ_FILES)
        else:
            conf.read(self.conf_file.as_posix(), encoding="utf-8")

        self.glob_prefix = conf.get(self._INI_CONFIG, self._INI_CONFIG_GLOB_PREFIX[0])
        self.glob_suffix = conf.get(self._INI_CONFIG, self._INI_CONFIG_GLOB_SUFFIX[0])
        self.cbz_prefix = conf.get(self._INI_CONFIG, self._INI_CONFIG_CBZ_PREFIX)
        self._LoadCbzSection(conf)

        return conf

    def SaveConfig(self, backup: bool = False):
        if backup:
            filepath = f"{self.conf_file.as_posix()}_{datetime.datetime.now().strftime(r'%Y%m%d%H%M%S')}.backup"
        else:
            filepath = self.conf_file.as_posix()
        with open(filepath, "w", encoding="utf-8") as f:
            self.conf.write(f)
        self.logger.debug(f'保存配置 "{filepath}"')

    def ShowCbzSection(self):
        self.logger.info(f"打包章节详情")
        self.logger.info(f"| 配置文件 {self.conf_file.as_posix()}")
        if len(self.cbz_tasks) == 0:
            self.logger.info(f"| 无 CBZ 文件")
            return
        for index, cbz in enumerate(self.cbz_tasks):
            self.logger.info(f'| [{index}] "{cbz.GetFileName()}"')
            self.logger.info(f"|  {' ' * len(str(index))}  总文件数 {len(cbz.GetFiles())} [{cbz.FormatChapterAndCount()}]")
        return

    def InsertCbz(self, config: ConfigParser, cbz: ComicPackage):
        config.set(self._INI_CBZ_FILES, cbz.cbz_name, cbz.FormatConfig())
        return

    def RemoveCbz(self, config: ConfigParser, cbz: ComicPackage):
        config.remove_option(self._INI_CBZ_FILES, cbz.cbz_name)
        return

    def _IsSplitPartStart(self, number: float, split_num: int, globle_start_num: int):
        return int(number % split_num) == globle_start_num

    def _IsOverflowPartEnd(self, number: float, split_num: int, part_first_num: float | int):
        return int(number % split_num) >= int(part_first_num + split_num)

    def _SplitChapterNumber(self, orm_chapters: List[database.ChapterORM], max_part_count: int, start_num: int):
        parse_list: List[List[PackageChapter]] = []
        parse_buf: List[PackageChapter] = []
        part_first_num = -1

        for orm_chapter in orm_chapters:
            if len(orm_chapter.group) == 0 or len(orm_chapter.name) == 0:
                self.logger.error(f'数据库索引 {orm_chapter.index:05d} 数据异常 "{orm_chapter.group}/{orm_chapter.name}" 将被忽略')
                continue

            chapter = PackageChapter.FromIdentifier(f"{orm_chapter.group}/{orm_chapter.name}")

            # 处理 单行本
            if chapter.name[-1] == "卷":
                if len(parse_buf) != 0:
                    parse_list.append(parse_buf)
                parse_list.append([chapter])
                parse_buf = []
                continue

            # 处理 话分割
            if chapter.number is not None and (
                # 遇到分割起点
                self._IsSplitPartStart(chapter.number, max_part_count, start_num)
                # 超过每段最大章节数
                or self._IsOverflowPartEnd(chapter.number, max_part_count, part_first_num)
            ):
                if len(parse_buf) != 0:
                    parse_list.append(parse_buf)
                parse_buf = [chapter]
                if chapter.number is None:
                    raise ValueError(f"章节分割起点不包含数字")
                part_first_num = chapter.number
                continue

            parse_buf.append(chapter)
            continue

        # 尾处理
        if len(parse_buf) != 0:
            parse_list.append(parse_buf)
        return parse_list

    def _SplitChapterFiles(self, orm_chapters: List[database.ChapterORM], max_file_count: int, start_num: int, start_count: int):
        parse_list: List[List[PackageChapter]] = []
        parse_buf: List[PackageChapter] = []
        file_count = start_count

        for orm_chapter in orm_chapters:
            if len(orm_chapter.group) == 0 or len(orm_chapter.name) == 0:
                self.logger.error(f'数据库索引 {orm_chapter.index:05d} 数据异常 "{orm_chapter.group}/{orm_chapter.name}" 将被忽略')
                continue

            chapter = PackageChapter.FromIdentifier(f"{orm_chapter.group}/{orm_chapter.name}")
            count = len(chapter.GetFiles(self.comic_dir, self.glob_prefix, self.glob_suffix))

            if count == 0:
                self.logger.warn(f"章节 {chapter.GetIdentifier()} 本地没有文件 将被忽略")
                continue

            # 处理 单行本
            if chapter.name[-1] == "卷":
                if len(parse_buf) != 0:
                    parse_list.append(parse_buf)
                parse_list.append([chapter])
                parse_buf = []
                file_count = 0
                continue

            # 处理 话
            if (
                (chapter.number is not None and int(chapter.number) == start_num and len(parse_buf) != 0)  #
                or file_count >= max_file_count
            ):
                parse_list.append(parse_buf)
                parse_buf = [chapter]
                file_count = count
                continue

            parse_buf.append(chapter)
            file_count += count
            continue

        # 尾处理
        if len(parse_buf) != 0:
            parse_list.append(parse_buf)

        return parse_list

    def _GetNewChapters(self, group: str):
        orm_chapters: List[database.ChapterORM] = []
        for orm_chapter in self.comic_db.chapter.ForceGroupGet(group):
            check_group = self.exist_groups.get(orm_chapter.group)
            # 分组不存在引用
            if check_group is None:
                orm_chapters.append(orm_chapter)
                continue
            # 章节不存在引用
            if check_group.get(orm_chapter.name) is None:
                orm_chapters.append(orm_chapter)
                continue
            # 章节已经被CBZ引用
            continue
        return orm_chapters

    def UpdateCbzInfo_SplitNumber(self, split_num: int, split_start: int):
        self.logger.debug(f"更新Cbz打包信息 按章节号分割(数量={split_num},起始={split_start})")
        self.conf = self._LoadConfig()

        def FindBelongCbz(number: float, split_num: int, split_start: int):
            for cbz in self.cbz_tasks:
                cbz_number = cbz.GetNumber()
                if cbz_number is None:
                    continue
                # 整除排序号 判断是否在同一组分割中
                if not (cbz_number - split_start) // split_num == (number - split_start) // split_num:
                    continue
                return cbz
            return None

        pack_list: List[List[PackageChapter]] = []
        for orm_group in self.comic_db.group.GetAll():
            new_chapters = self._GetNewChapters(orm_group.name)
            pack_list += self._SplitChapterNumber(new_chapters, split_num, split_start)

        if len(pack_list) == 0:
            self.logger.info(f"无内容更新")

        for pack in pack_list:
            sort, nosort = PackageChapter.Sort(pack)
            if len(sort) == 0 and len(nosort) == 0:
                raise IndexError(f"排序结果为空{pack}")
            pack_number = sort[0].number

            # 结果不能数字排序
            if pack_number is None:
                continue

            # 查找属于哪个CBZ
            cbz = FindBelongCbz(pack_number, split_num, split_start)

            # 新建CBZ
            if cbz is None:
                cbz = ComicPackage(
                    self.comic_dir,
                    self.output_dir,
                    self.comic_name,
                    "null",
                    self.glob_prefix,
                    self.glob_suffix,
                )
                groups = cbz.groups
                self.logger.info(f"新建 {cbz}")
                for index, chapter in enumerate(pack):
                    group = chapter.group
                    if groups.get(group) is None:
                        groups[group] = {}
                    chapters = groups[group]
                    chapters[chapter.name] = chapter
                    self.logger.info(f"| + {chapter}")
                    continue
                cbz.AutoSetName()
                self.logger.info(f"| 更新名称 {cbz.cbz_name}")
                self.conf.set(self._INI_CBZ_FILES, cbz.cbz_name, cbz.FormatConfig())

            # 插入CBZ
            else:
                self.logger.info(f"插入 {cbz}")
                for index, chapter in enumerate(pack):
                    self.logger.info(f"| + {chapter}")
                    cbz.groups[chapter.group][chapter.name] = chapter
                    continue
                cbz.AutoSetName()
                self.logger.info(f"| 更新名称 {cbz.cbz_name}")
                self.conf.set(self._INI_CBZ_FILES, cbz.cbz_name, cbz.FormatConfig())

            continue

        self.SaveConfig()
        self.conf = self._LoadConfig()
        return

    def UpdateCbzInfo_SplitFiles(self, max_file_count: int, split_start: int):
        self.logger.debug(f"更新Cbz打包信息 按文件数分割(数量={max_file_count},起始={split_start})")
        self.conf = self._LoadConfig()

        def FindNoFullCbz(max_file_count: int):
            r: List[ComicPackage] = []
            for cbz in self.cbz_tasks:
                count = len(cbz.GetFiles())
                if count >= max_file_count:
                    continue
                r.append(cbz)
            return r

        def FindBelongCbz(number: float, max_file_count: int):
            for cbz in FindNoFullCbz(max_file_count):
                nums = cbz.GetNumberAll()
                if nums is None:
                    continue
                last_num = nums[-1]
                if number - last_num > 1:
                    self.logger.warn(f"当前章节号 {number} 未继续 {cbz}")
                    return None
                return cbz
            return None

        check_cbz = FindNoFullCbz(max_file_count)

        if len(check_cbz) > 1:
            self.logger.warn(f"存在多个文件数未满CBZ 无法判断插入点")
            for cbz in check_cbz:
                self.logger.warn(f"| {cbz}")
            start_count = 0
        elif len(check_cbz) == 0:
            start_count = 0
        else:
            cbz = check_cbz[0]
            self.logger.warn(f"从CBZ开始文件计数 {cbz}")
            start_count = len(cbz.GetFiles())

        pack_list: List[List[PackageChapter]] = []
        for orm_group in self.comic_db.group.GetAll():
            new_chapters = self._GetNewChapters(orm_group.name)
            pack_list += self._SplitChapterFiles(new_chapters, max_file_count, split_start, start_count)

        for pack in pack_list:
            sort, nosort = PackageChapter.Sort(pack)
            if len(sort) == 0 and len(nosort) == 0:
                raise IndexError(f"排序结果为空{pack}")
            pack_number = sort[0].number

            # 结果不能数字排序
            if pack_number is None:
                continue

            # 查找属于哪个CBZ
            cbz = FindBelongCbz(pack_number, max_file_count)

            # 新建CBZ
            if cbz is None:
                cbz = ComicPackage(
                    self.comic_dir,
                    self.output_dir,
                    self.comic_name,
                    "null",
                    self.glob_prefix,
                    self.glob_suffix,
                )
                groups = cbz.groups
                self.logger.info(f"新建 {cbz}")
                for index, chapter in enumerate(pack):
                    group = chapter.group
                    if groups.get(group) is None:
                        groups[group] = {}
                    chapters = groups[group]
                    chapters[chapter.name] = chapter
                    self.logger.info(f"| + {chapter}")
                    continue
                cbz.AutoSetName()
                self.logger.info(f"| 更新 名称={cbz.cbz_name} 内容={cbz.FormatConfig()}")
                self.conf.set(self._INI_CBZ_FILES, cbz.cbz_name, cbz.FormatConfig())

            # 插入CBZ
            else:
                self.logger.info(f"插入 {cbz}")
                for index, chapter in enumerate(pack):
                    self.logger.info(f"| + {chapter}")
                    cbz.groups[chapter.group][chapter.name] = chapter
                    continue
                cbz.AutoSetName()
                self.logger.info(f"| 更新 名称={cbz.cbz_name} 内容={cbz.FormatConfig()}")
                self.conf.set(self._INI_CBZ_FILES, cbz.cbz_name, cbz.FormatConfig())

            continue

        self.SaveConfig()
        self.conf = self._LoadConfig()
        return

    def UpdateCbzInfo(self, mode: int, split_num: int, split_start: int):
        self.conf = self._LoadConfig()

        if mode == 1:
            self.UpdateCbzInfo_SplitNumber(split_num, split_start)
        elif mode == 2:
            self.UpdateCbzInfo_SplitFiles(split_num, split_start)
        else:
            raise ValueError(f"不支持的更新模式{mode}")

        return

    def _CreateCbz(self, path: Path, files: List[Path]):
        with zipfile.ZipFile(path.as_posix(), "w", zipfile.ZIP_DEFLATED) as z:
            for file in files:
                z.write(file.resolve().as_posix(), file.name)
                continue
            pass
        return

    def OutputAllPackage(self):
        self.logger.debug(f"导出Cbz文件")
        self.conf = self._LoadConfig()
        result: List[ComicPackage] = []
        for cbz in self.cbz_tasks:
            cbz_path = self.output_dir.as_posix() / cbz.GetFileName()
            cbzinfo = self.conf.get(self._INI_CBZ_FILES, cbz.cbz_name)
            if "#" in cbzinfo[: cbzinfo.find("[")]:
                self.logger.warn(f"| 跳过 {cbz.GetFileName()} 打包")
                continue
            if cbz_path.exists():
                if cbz_path.is_dir():
                    self.logger.error(f"| 路径被文件夹占用 {cbz_path.as_posix()} 失败")
                    continue
                self.logger.info(f"| 移除旧文件 {cbz.GetFileName()}")
                cbz_path.unlink(missing_ok=True)

            self.logger.info(f"| {cbz_path.as_posix()} 写入")
            files: List[Path] = []
            for group in cbz.groups.values():
                for chapter in group.values():
                    chapter_files = chapter.GetFiles(self.comic_dir, self.glob_prefix, self.glob_suffix)
                    self.logger.info(f"| + 文件数:{len(chapter_files)} {chapter.GetIdentifier()} ")
                    files += chapter_files
                    continue
                continue
            self._CreateCbz(cbz_path, files)
            cbz_size = cbz_path.stat().st_size
            file_size = 0.0
            for file in files:
                file_size += file.stat().st_size
            cbzinfo = "# " + cbzinfo
            self.conf.set(self._INI_CBZ_FILES, cbz.cbz_name, cbzinfo)
            self.logger.info(f'| > 更新配置 " {cbzinfo} "')
            self.logger.info(f"| = 打包完成 {cbz_size / 1000 / 1000:.2f} MB 压缩率 {(file_size / cbz_size) * 100:.2f}%")
            self.SaveConfig()
            result.append(cbz)
            continue
        if len(result) == 0:
            self.logger.info(f"无文件更改")
            return
        self.logger.info(f"文件更改")
        for index, cbz in enumerate(result):
            self.logger.info(f"| [{index}] {cbz.GetFileName()}")
        self.logger.info(f"打包完成")
        return


def module_test():
    packer = FilePacker(
        CBZ_ROOT,
        DOWNLOAD_ROOT,
        DB_ROOT,
        "silentwitchchenmodemonvdemimi",
    )
    packer.ShowCbzSection()
    packer.UpdateCbzInfo_SplitNumber(10, 0)
    packer.OutputAllPackage()


if __name__ == "__main__":
    os.system("cls")
    os.system("chcp 65001")
    module_test()
