import os
import time
import winreg
import traceback

from pathlib import Path
from typing import List, Tuple

import database
import aria2tool
import dlmanager
import packer
from copymanga import CopymangaObject


DB_ROOT = Path("db.nosync")
DOWNLOAD_ROOT = Path("dl.nosync")
CBZ_ROOT = Path("cbz.nosync")
TEMP_ROOT = Path("temp.nosync")

DB_ROOT.mkdir(parents=True, exist_ok=True)
DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
TEMP_ROOT.mkdir(parents=True, exist_ok=True)
CBZ_ROOT.mkdir(parents=True, exist_ok=True)

FILE_PREFIX = "*."
FILE_SUFFIX = "-*.*"


class win32proxy:
    def __init__(self) -> None:
        self.__path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        self.__INTERNET_SETTINGS = winreg.OpenKeyEx(winreg.HKEY_CURRENT_USER, self.__path, 0, winreg.KEY_ALL_ACCESS)

    def get_proxy(self) -> str | None:
        ip_port = str()
        if self.is_open_proxy():
            try:
                ip_port = winreg.QueryValueEx(self.__INTERNET_SETTINGS, "ProxyServer")[0]
                return str(ip_port)
            except Exception as e:
                print(e)
        return None

    def is_open_proxy(self) -> bool:
        try:
            if winreg.QueryValueEx(self.__INTERNET_SETTINGS, "ProxyEnable")[0] == 1:
                return True
        except Exception as e:
            print(e)
        return False


def ClearDir(path: Path) -> int:
    remove_count = 0
    for item in path.iterdir():
        if item.is_file():
            item.unlink()
            remove_count += 1
        else:
            remove_count += ClearDir(item)
    return remove_count


def SizeDir(path: Path) -> int:
    total_size = 0
    for item in path.iterdir():
        if item.is_file():
            total_size += item.stat().st_size
        else:
            total_size += SizeDir(item)
    return total_size


PROXY = win32proxy().get_proxy()


class Console:
    class Command:
        def __init__(self, is_all: bool, call, argv: List[str], desc: str) -> None:
            self.support_all = is_all
            self.argv = argv
            self.call = call
            self.desc = desc

        def GetArgc(self):
            return len(self.argv) + 1

    def __init__(self, temp_root: Path, download_root: Path, database_root: Path, proxy: None | str) -> None:
        self.comics: List[Tuple[str, str]] = []
        self.temp_root = temp_root
        self.download_root = download_root
        self.database_root = database_root
        self.proxy = proxy

        self.exit_status = False
        self.commands_str: str = ""

        Command = self.Command

        self.commands = {
            "help": Command(True, self.Cmd_Help, [], "显示命令列表"),
            "update": Command(True, self.Cmd_Update, ["index"], "更新数据库"),
            "download": Command(True, self.Cmd_Download, ["index"], "下载文件"),
            "scan": Command(True, self.Cmd_Detect, ["index"], "标记存在的文件到已下载"),
            "check": Command(True, self.Cmd_Check, ["index"], "检查本地文件"),
            "pack-info": Command(True, self.Cmd_PackComicInfo, ["index"], "显示漫画打包信息"),
            "pack-update": Command(True, self.Cmd_PackComicUpdate, ["num", "start", "index"], "更新漫画打包信息 num=打包分割章节号 start=起始章节号"),
            "pack-run": Command(True, self.Cmd_PackComicRun, ["index"], "打包漫画"),
            "show": Command(False, self.Cmd_Show, ["index"], "显示详细信息"),
            "mark": Command(False, self.Cmd_Mark, ["index"], "标记已下载但不存在的文件"),
            "delete": Command(False, self.Cmd_DeleteDatabase, ["index"], "删除数据库"),
            "search": Command(False, self.Cmd_Search, ["keyword"], "使用关键词搜索并创建数据库"),
            "init": Command(False, self.Cmd_Init, ["pathword"], "使用路径词创建数据库"),
            "list": Command(False, self.ShowComic, [], "显示漫画列表"),
            "clear": Command(False, self.Cmd_Clear, [], "清除控制台历史输出"),
            "exit": Command(False, self.Cmd_Exit, [], "退出 或 双击Ctrl+C"),
        }

        self.FormatCommands()
        return

    def FormatCommands(self):
        arg_list: List[str] = []
        desc_list: List[str] = []
        for command1 in self.commands.keys():
            detail = self.commands[command1]
            arg = f"{command1} "
            for value in detail.argv:
                if detail.support_all and value == "index":
                    arg += f"[{value}/all] "
                    continue
                arg += f"[{value}] "
                continue
            arg_list.append(arg)
            desc_list.append(detail.desc)
            continue

        arg_length = 0
        for arg in arg_list:
            arg_length = max(arg_length, len(arg))

        self.commands_str: str = ""
        for arg, desc in zip(arg_list, desc_list):
            self.commands_str += f"┃ {arg:{arg_length}s}    {desc}\n"

        return

    def ScanComics(self):
        self.comics.clear()

        for db_file in self.database_root.glob(f"*.db"):
            pathword = "UnknownPathword"
            name = "UnknownDisplay"
            print(f"加载数据库 {db_file.as_posix()}")
            try:
                db = database.ComicDatabase(db_file)
                name = db.attribute.GetName()
                pathword = db.attribute.GetPathword()
            except Exception as e:
                print(f"错误 {e}")
                print(f"无法读取数据库 {db_file.resolve().as_posix()}")
                continue

            local_storage = Path(f"{self.download_root}/{name}")

            if local_storage.exists():
                size = ""
                # size = f"{SizeDir(local_storage) / 1000000:.1f} MiB"
            else:
                size = "无本地文件"

            self.comics.append((pathword, f"{name} | {size}"))
            continue
        
        print()
        return

    def ConvertIndex(self, cmd: str, num: str):
        try:
            index = int(num, 10)

        except Exception:
            print(f" {cmd} 参数 index={num} 不是十进制数字.")
            return None

        if index < 0 or index >= len(self.comics):
            print(f" {cmd} 参数 index={index} 索引值超出范围.")
            return None

        return index

    def _CopymangaIndex(self, i: int):
        return self._CopymangaPathword(self.comics[i][0])

    def _CopymangaPathword(self, pathword: str):
        return CopymangaObject(
            download_root=self.download_root,
            database_root=self.database_root,
            pathword=pathword,
            proxy=self.proxy,
        )

    def _CopymangaKeyword(self, keyword: str):
        return CopymangaObject(
            download_root=self.download_root,
            database_root=self.database_root,
            keyword=keyword,
            proxy=self.proxy,
        )

    def Cmd_All(self, argv: List[str], call):
        cmd = argv[0]
        index = argv[1]
        if index == "all":
            for pathword, _ in self.comics:
                call(pathword)
                print()
            return
        num = self.ConvertIndex(cmd, index)
        if num is None:
            return
        call(self.comics[num][0])
        return

    def Cmd_Help(self, argv: List[str]):
        self.ShowCommand(argv)

    def Cmd_Update(self, argv: List[str]):
        def Update(pathword: str):
            comic = self._CopymangaPathword(pathword)
            comic.ShowMetadate()
            comic.UpdateAll(not_files=False)
            return

        return self.Cmd_All(argv, Update)

    def Cmd_Download(self, argv: List[str]):
        def Download(pathword: str):
            server = aria2tool.Aria2Server("dl.nosync", 99)
            server.Restart()
            manger = dlmanager.CopymangaDLManger(
                aria2tool.Aria2Client(server.Url(), server.Token()),
                database.ComicDatabase(self.database_root / Path(f"{pathword}.db")),
                self.proxy,
                self.download_root,
                self.temp_root,
            )
            try:
                manger.Run(auto_exit=True)
            except Exception as e:
                print(f"下载时发送错误: {e}")
            finally:
                server.Stop()
            return

        return self.Cmd_All(argv, Download)

    def Cmd_Detect(self, argv: List[str]):
        def Detect(pathword: str):
            comic = self._CopymangaPathword(pathword)
            comic.ShowMetadate()
            comic.DetectFiles()
            return

        return self.Cmd_All(argv, Detect)

    def Cmd_Check(self, argv: List[str]):
        def Check(pathword: str):
            comic = self._CopymangaPathword(pathword)
            comic.ShowMetadate()
            comic.CheckFiles()
            return

        return self.Cmd_All(argv, Check)

    def Cmd_PackComicInfo(self, argv: List[str]):
        def Show(pathword: str):
            packer.FilePacker(
                CBZ_ROOT,
                DOWNLOAD_ROOT,
                DB_ROOT,
                pathword,
            ).ShowCbzSection()
            return

        return self.Cmd_All(argv, Show)

    def Cmd_PackComicUpdate(self, argv: List[str]):
        split_num = int(argv[1])
        split_start = int(argv[2])

        def Update(pathword: str):
            packer.FilePacker(
                CBZ_ROOT,
                DOWNLOAD_ROOT,
                DB_ROOT,
                pathword,
            ).UpdateCbzInfo_SplitNumber(
                split_num,
                split_start,
            )
            return

        pathword = argv[3]
        return self.Cmd_All(["pack-update", pathword], Update)

    def Cmd_PackComicRun(self, argv: List[str]):
        def Output(pathword: str):
            packer.FilePacker(
                CBZ_ROOT,
                DOWNLOAD_ROOT,
                DB_ROOT,
                pathword,
            ).OutputAllPackage()
            return

        return self.Cmd_All(argv, Output)

    def Cmd_Mark(self, argv: List[str]):
        num = self.ConvertIndex(argv[0], argv[1])
        if num is None:
            return
        comic = self._CopymangaIndex(num)
        comic.ShowMetadate()
        comic.CheckFiles(mark_removed_file=True)
        return

    def Cmd_Show(self, argv: List[str]):
        num = self.ConvertIndex(argv[0], argv[1])
        if num is None:
            return
        comic = self._CopymangaIndex(num)
        comic.ShowMetadate()
        comic.UpdateAll(not_files=True)
        return

    def Cmd_DeleteDatabase(self, argv: List[str]):
        num = self.ConvertIndex(argv[0], argv[1])
        if num is None:
            return
        comic = self._CopymangaIndex(num)
        check_delete = input(f"删除 {comic.database} 数据库文件 输入[Yes]确认操作(区分大小写)=")
        if check_delete == "Yes":
            db = comic.database.GetDatabaseFilePath()
            print(f'保留本地目录 "{(self.download_root / Path(comic.comic.name)).as_posix()}"')
            del comic
            db.unlink()
        else:
            print(f"取消删除数据库")
        return

    def Cmd_Search(self, argv: List[str]):
        cmd = argv[1]
        keyword = argv[1]
        if len(keyword) == 0:
            print(f" {cmd} keyword为空 未输入任何关键词.")
            return
        comic = self._CopymangaKeyword(keyword)
        print(f"增加 {comic.comic.name} / {comic.comic.path_word}")
        return

    def Cmd_Init(self, argv: List[str]):
        cmd = argv[1]
        pathword = argv[1]
        if len(pathword) == 0:
            print(f" {cmd} pathword为空 未输入任何关键词.")
            return

        comic = self._CopymangaPathword(pathword)
        print(f"增加 {comic.comic.name} / {comic.comic.path_word}")
        return

    def Cmd_Clear(self, argv: List[str]):
        os.system("cls")

    def Cmd_Exit(self, argv: List[str]):
        self.exit_status = True

    def ShowCommand(self, argv: List[str] | None = None):
        print()
        print("┏━━━━━━ 所有命令")
        print(self.commands_str, end="")
        print("┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    def ShowComic(self, argv: List[str] | None = None):
        print()
        self.ScanComics()

        if len(self.comics) == 0:
            print("[ 无漫画 ]")
            return
        print("┏━━━━━━ 漫画列表")
        for i, data in enumerate(self.comics):
            path_word = data[0]
            manga_name = data[1]
            print(f"┃ {str(i).zfill(2)}. [ {manga_name} | {path_word} ] ")
        print("┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        return

    def Run(self):
        
        self.ShowComic()
        self.ShowCommand()
        self.exit_status = False

        def Loop():
            while not self.exit_status:
                input_str = input("> ")
                if len(input_str) == 0:
                    continue
                argv = input_str.split()
                cmd = argv[0]
                detail = self.commands.get(cmd)
                if detail is None:
                    print(f' 未知命令 "{cmd}" .')
                    continue
                if len(argv) != detail.GetArgc():
                    print(f" 命令 {cmd} 参数不正确.")
                    continue
                detail.call(argv)
                continue

        while not self.exit_status:
            try:
                Loop()
            except KeyboardInterrupt:
                print("\n用户中断操作 双击Ctrl+C退出")
                time.sleep(1)
                continue
            except Exception as e:
                traceback.print_exc()
                print(f"错误：{e}")


if __name__ == "__main__":
    os.system("cls")
    os.system("chcp 65001")

    try:
        Console(
            TEMP_ROOT,
            DOWNLOAD_ROOT,
            DB_ROOT,
            PROXY,
        ).Run()
    except KeyboardInterrupt:
        exit()
    except Exception as e:
        raise e
