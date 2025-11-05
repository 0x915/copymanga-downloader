import datetime
import threading

from pathlib import Path
import time
from typing import List, Optional, Sequence, Tuple

import database
import aria2tool

import spdlogger

from copymanga import ComicFilePath

logger = spdlogger.logger


def ClearDir(path: Path) -> int:
    remove_count = 0
    for item in path.iterdir():
        if item.is_file():
            item.unlink()
            remove_count += 1
        else:
            remove_count += ClearDir(item)
    return remove_count


class RequsetCountLock:
    def __init__(self, num: int) -> None:
        self._queue: List[datetime.datetime] = []
        self._lock = threading.Lock()
        self._num = num

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
        return f"{len(self._queue)}/{self._num}"


globle_max_download_request_num = 99
globle_download_request_lock = RequsetCountLock(globle_max_download_request_num)


class Task:
    LOAD_Error_InvalidUrl = -255
    LOAD_Error_PathProblem = -1
    LOAD_Succ_WaitSmbmit = 0

    def __init__(
        self,
        aria2_client: aria2tool.Aria2Client,
        download_dir: Path,
        temp_dir: Path,
    ) -> None:
        self.err_cnt: int = 0
        self.last_dlsize: int = 0
        self.last_updated = datetime.datetime.now()

        self.url: str = ""

        self.gid: Optional[str] = None

        self.orm_bind: int = -1
        self.aria2_client: aria2tool.Aria2Client = aria2_client
        self.proxy: Optional[str] = None

        self.filepath = Path()
        self.download_dir = Path(download_dir)
        self.temp_dir = Path(temp_dir)

        self.logger = logger.ObjLogger(self)
        return

    def __str__(self):
        return f'<Task bind={self.orm_bind} file="{self.filepath.as_posix()}" gid={self.gid}>'

    def GetSaveFullPath(self):
        return self.download_dir / self.filepath

    def GetTempFullPath(self):
        return self.temp_dir / self.filepath

    def LoadOrmFile(self, obj: database.FileORM):
        if self.gid is not None:
            self.Stop()

        # 检查下载地址
        self.url = obj.dl_url
        if not self.url.startswith("http"):
            self.logger.error(f"非法URL {self.url}")
            return Task.LOAD_Error_InvalidUrl

        # 获取文件相对下载路径
        self.filepath = Path(ComicFilePath.AtDownloadDir_ORM(obj))

        # 检查文件
        checkfile = self.GetSaveFullPath()
        if checkfile.exists():
            if checkfile.is_dir():
                self.logger.error(f'文件保存路径 "{checkfile.as_posix()}" 被目录占用')
                return Task.LOAD_Error_PathProblem
            if checkfile.is_file():
                self.logger.debug(f'删除文件 "{checkfile.as_posix()}"')
                checkfile.unlink()
            pass

        # 检查文件
        checkfile = self.GetTempFullPath()
        if checkfile.exists():
            if checkfile.is_dir():
                self.logger.error(f'缓存文件路径 "{checkfile.as_posix()}" 被目录占用')
                return Task.LOAD_Error_PathProblem
            if checkfile.is_file():
                self.logger.debug(f'删除缓存 "{checkfile.as_posix()}"')
                checkfile.unlink()
            pass

        return Task.LOAD_Succ_WaitSmbmit

    def Status(self) -> aria2tool.RpcStructStatus | None:
        if self.gid is None:
            return None
        return self.aria2_client.TellStatus(self.gid)

    def Stop(self) -> bool:
        if self.gid is None:
            self.logger.warn(f"{self} 没有绑定下载实例")
            return False
        self.logger.debug(f"移除 {Task}")
        self.aria2_client.Remove(self.gid)
        self.gid = None
        return True

    def Start(self) -> bool:
        if self.gid is not None:
            self.logger.warn(f"{self} 已经绑定下载实例")
            return False
        # 检查下载目录
        cahce = self.GetTempFullPath()
        cahce.parent.mkdir(parents=True, exist_ok=True)
        # 提交下载请求
        self.gid = self.aria2_client.AddUri(
            url=self.url,
            savepath=cahce.parent.as_posix(),
            filename=cahce.name,
            proxy=self.proxy,
        )
        self.logger.debug(f'提交 {self.gid} -> "{cahce.as_posix()}"')
        return True

    def Save(self) -> bool:
        status = self.Status()
        if status is None:
            return False
        if status.status != "complete":
            return False
        # 检查保存目录
        save = self.GetSaveFullPath()
        save.parent.mkdir(parents=True, exist_ok=True)
        # 移动缓存文件
        file = self.GetTempFullPath()
        file.rename(save)
        self.logger.info(f'完成 {self.gid} -> "{save.as_posix()}"')
        return True


class CopymangaDLManger:
    #

    def __init__(
        self,
        aria2_client: aria2tool.Aria2Client,
        sql_client: database.ComicDatabase,
        proxy: Optional[str],
        download_dir: Path,
        temp_dir: Path,
    ) -> None:
        self.logger = logger.ObjLogger(self)
        self.proxy = proxy

        self.max_task_num = 20
        self.active_tasks: List[Task] = []
        self.lock = globle_download_request_lock

        self.aria2_client = aria2_client
        self.database = sql_client

        self.thread_exit: bool = False

        self.name = self.database.attribute.GetName()
        self.pathwordname = self.database.attribute.GetPathword()
            
        self.temp_dir = temp_dir / Path(self.name)
        self.download_dir = download_dir / Path(self.name)

        self.logger.debug(f'缓存目录 = "{self.temp_dir.as_posix()}"')
        self.logger.debug(f'下载目录 = "{self.download_dir.as_posix()}"')

        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        ClearDir(self.temp_dir)

        self.is_throttled = False
        self.is_finished = False
        return

    def TaskCompleted(self, task: Task):
        if not task.Save():
            self.logger.error(f"{task} 无法移动缓存")
            return False
        self.database.file.Set_DlStatus_Completed(task.orm_bind)
        return True

    def TaskTryfix(self, task: Task):
        task.Stop()
        if task.err_cnt >= 5:
            self.logger.error(f"{task} 失败")
            return False
        else:
            task.err_cnt += 1
            self.logger.warn(f"{task} 重试第 {task.err_cnt} 次")
            return task.Start()

    def ActiveQueueFull(self):
        return len(self.active_tasks) >= self.max_task_num

    def ActiveQueueZero(self):
        return len(self.active_tasks) == 0

    def CreateTask(self, file: database.FileORM):
        # 新建下载任务
        task = Task(
            self.aria2_client,
            self.download_dir,
            self.temp_dir,
        )

        status = task.LoadOrmFile(file)
        # 开始下载 标记到数据库
        if status == Task.LOAD_Succ_WaitSmbmit:
            file.dl_status = database.File.DlStatus.Active
            self.database.Commit()
            task.orm_bind = file.index
            task.Start()
            self.lock.CountAdd()
            self.active_tasks.append(task)
            return True
        # 非法URL 标记到数据库
        elif status == Task.LOAD_Error_InvalidUrl:
            file.dl_status = database.File.DlStatus.InvalidUrl
            file.dl_skip = True
            self.database.Commit()
            return False
        # 路径故障 标记到数据库
        elif status == Task.LOAD_Error_PathProblem:
            file.dl_status = database.File.DlStatus.Error
            self.database.Commit()
        else:
            raise ValueError(f"task: load orm return status {status}")
        self.logger.error(f"创建任务失败 {task} ")
        return False

    def AddFiles(self, files: List[database.FileORM]):
        if self.ActiveQueueFull():
            return False

        if len(files) == 0:
            return None

        if not self.lock.Ready():
            sec = self.lock.ReleaseTime()
            if self.is_throttled is False and sec != 0:
                self.logger.debug(f"等待DL请求数 {self.lock.ReleaseTime()}s")
            self.is_throttled = True
            return False

        self.is_throttled = False
        file = files.pop(0)

        status = self.CreateTask(file)

        return status

    def AddFile(self, dl_status: int = database.File.DlStatus.Wait):
        if self.ActiveQueueFull():
            return False

        file = self.database.file.GetFirst(
            database.FileOptional(dl_status=dl_status),
        )

        if file is None:
            return None

        # 限制API请求次数
        if not self.lock.Ready():
            sec = self.lock.ReleaseTime()
            if self.is_throttled is False and sec != 0:
                self.logger.debug(f"等待DL请求数 {self.lock.ReleaseTime()}s")
            self.is_throttled = True
            return False

        self.is_throttled = False
        status = self.CreateTask(file)
        return status

    def PrintCheckTasks(self):
        rm_tasks: List[Task] = []

        progress_bar = str()

        for task in self.active_tasks:
            # 获取任务状态
            status = task.Status()
            if status is None:
                raise ValueError

            # 获取百分比
            if status.totalLength == 0:
                rate_str = f"00 "
            else:
                rate = int((status.completedLength / status.totalLength) * 100)
                if rate == 100:
                    rate_str = f"=="
                else:
                    rate_str = f"{str(rate).zfill(2)} "

            # 下载完成
            if status.status == "complete" and self.TaskCompleted(task):
                rm_tasks.append(task)
                progress_bar += f"-- "

            # 下载出现错误 重试五次后放弃
            elif status.status == "error" and self.TaskTryfix(task):
                progress_bar += f"ER "

            # 下载中
            elif status.status == "active":
                progress_bar += rate_str

            # 其他状态
            else:
                progress_bar += f"{status.status[0:1].upper()} "

            continue

        # 填充进度条
        fill = self.max_task_num - len(self.active_tasks)
        progress_bar += f"-- " * fill

        status = self.aria2_client.GetGlobalStat()
        active_fmt = f"活动({status.numActive})"
        speed_fmt = f"{int(status.downloadSpeed / 1000)} KB/s"

        throttled = ""
        if self.is_throttled and self.lock.ReleaseTime() != 0:
            throttled = f":{self.lock.ReleaseTime():02d}s"

        self.logger.info(f"[ {progress_bar}] 任务数({len(self.active_tasks)}/{self.max_task_num}) 请求数({self.lock}{throttled}) {active_fmt} {speed_fmt}")

        # 移除已完成和放弃的任务
        for task in rm_tasks:
            self.active_tasks.remove(task)

        return len(rm_tasks)

    def DownloadMulti(self, dl_status: int):
        files = self.database.file.GetAll(
            database.FileOptional(dl_status=dl_status),
        )

        if len(files) == 0:
            self.logger.debug(f"没有可下载的文件")
            return

        self.logger.info(f"下载 {len(files)} 个文件")

        is_finished = False
        while True:
            #
            if self.AddFiles(files) is None:
                is_finished = True

            if is_finished and self.ActiveQueueZero():
                break

            if (  # 有待下载文件+队列空闲+有请求数 继续增加任务
                not is_finished  #
                and not self.ActiveQueueFull()
                and not self.is_throttled
            ):
                continue

            self.PrintCheckTasks()
            time.sleep(1)
            continue
        return

    def DownloadFirst(self, dl_status: int):
        is_finished = False
        while True:
            #
            if self.AddFile(dl_status) is None:
                is_finished = True

            if is_finished and self.ActiveQueueZero():
                break

            if (  # 未完成/队列空闲/有请求数 继续增加任务
                not is_finished  #
                and not self.ActiveQueueFull()
                and not self.is_throttled
            ):
                continue

            self.PrintCheckTasks()
            time.sleep(1)
            continue

        self.logger.debug(f"无下一个文件")
        return

    def Download_Unfinished(self):
        self.logger.info(f"检查未完成文件")
        status = self.aria2_client.GetGlobalStat()
        if status.numActive != 0:
            self.logger.error("下载服务中还有正在下载的任务 禁止检查数据库未完成文件")
            return
        return self.DownloadMulti(database.File.DlStatus.Active)

    def Download_NewFile(self):
        self.logger.info(f"检查未新文件")
        return self.DownloadFirst(database.File.DlStatus.Wait)

    def Download_PathProblemFile(self):
        self.logger.info(f"检查一般故障文件")
        return self.DownloadMulti(database.File.DlStatus.Error)

    def Run(self, auto_exit: bool = False):
        self.thread_exit = False

        while not self.thread_exit:
            #
            self.Download_Unfinished()
            self.Download_NewFile()
            self.Download_PathProblemFile()

            if auto_exit:
                self.logger.info(f"下载完成")
                break

            continue

        return


def module_test():
    from main import win32proxy, DB_ROOT, DOWNLOAD_ROOT, TEMP_ROOT

    server = aria2tool.Aria2Server("dl.nosync", 99)
    server.Restart()

    manger = CopymangaDLManger(
        aria2tool.Aria2Client(server.Url(), server.Token()),
        database.ComicDatabase(DB_ROOT / Path(f"silentwitchchenmodemonvdemimi.db")),
        win32proxy().get_proxy(),
        DOWNLOAD_ROOT,
        TEMP_ROOT,
    )

    try:
        manger.Run(auto_exit=True)

    except Exception as e:
        raise e

    finally:
        server.Stop()


if __name__ == "__main__":
    module_test()
