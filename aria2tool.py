from io import BufferedWriter, TextIOWrapper
import os
import json
import random
import socket
import string
import secrets
import requests
import subprocess

from typing import Dict, List, Literal, Optional, TypedDict
from pathlib import Path
from pydantic import BaseModel
from spdlogger import logger


def CheckHostPortIdle(port: int):
    if port == 0:
        return False
    if port <= 1024 or port >= 65536:
        raise ValueError
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(1)
        s.connect(("localhost", port))
        s.close()
        port_idle = False
    except Exception:
        port_idle = True
        pass
    return port_idle


data = Path("./data")
data.mkdir(exist_ok=True)


class Aria2Server:
    def __init__(self, dl_dir: str, dl_max: int) -> None:
        self.logger = logger.ObjLogger(self)
        self._port: int = int(6800)
        self._token: str = str()

        while True:
            if CheckHostPortIdle(self._port) is True:
                break
            self._port = random.randint(1024, 65536)
            continue

        for _ in range(64):
            self._token += secrets.choice(
                string.ascii_letters  #
                + string.digits
            )

        self._exec = "aria2c"
        self._args = [
            "--disk-cache=32M",
            f"--dir={dl_dir}",
            f"--max-concurrent-downloads={dl_max}",
            "--file-allocation=prealloc",
            # 禁用断点续传
            "--continue=false",
            # 禁用分片多线程
            "--split=1",
            # 失败重试
            "--timeout=10",
            "--max-tries=5",
            "--retry-wait=0",
            # RPC控制
            "--enable-rpc=true",
            "--rpc-allow-origin-all=true",
            "--rpc-listen-all=false",
            f"--rpc-listen-port={self._port}",
            f"--rpc-secret={self._token}",
        ]

        self._stdout_logfile = data / Path("aria2c-server.0.stdout.log")
        self._stderr_logfile = data / Path("aria2c-server.0.stderr.log")

        count = 0
        while self._stdout_logfile.exists() or self._stderr_logfile.exists():
            count += 1
            self._stdout_logfile = data / Path(f"aria2c-server.{count}.stdout.log")
            self._stderr_logfile = data / Path(f"aria2c-server.{count}.stderr.log")

        self._stdout_bufw: Optional[BufferedWriter] = None
        self._stderr_bufw: Optional[BufferedWriter] = None
        self._process: Optional[subprocess.Popen] = None

        self.logger.info(f"初始化下载服务 {self.Port()} {self.Token()}")
        self.logger.debug(f"stdout -> {self._stdout_logfile.as_posix()}")
        self.logger.debug(f"stderr -> {self._stderr_logfile.as_posix()}")

    def Token(self):
        return str(self._token)

    def Host(self):
        return "http://localhost"

    def Port(self):
        return int(self._port)

    def Url(self):
        return f"{self.Host()}:{self.Port()}"

    def Cmd(self):
        cmd = str(self._exec)
        for i in self._args:
            cmd += " " + i
        return cmd

    def Stop(self):
        if self._process is None:
            return
        if self._process.poll() is None:
            self._process.kill()
        self._process = None
        if self._stdout_bufw is not None:
            self._stdout_bufw.close()
            self._stdout_bufw = None
        if self._stderr_bufw is not None:
            self._stderr_bufw.close()
            self._stderr_bufw = None
        self.logger.debug(f"下载服务已停止")
        return

    def Restart(self):
        if self._process is not None:
            self.Stop()
        self._stdout_logfile.unlink(missing_ok=True)
        self._stderr_logfile.unlink(missing_ok=True)
        self._stdout_bufw = open(self._stdout_logfile.as_posix(), "wb")
        self._stderr_bufw = open(self._stderr_logfile.as_posix(), "wb")
        self._process = subprocess.Popen(
            args=self.Cmd(),
            shell=False,
            stdout=self._stdout_bufw,
            stderr=self._stderr_bufw,
        )
        self.logger.debug(f"启动下载服务进程 PID{self._process.pid} {self._process}")
        return

    def isRuning(self) -> bool:
        if self._process is None:
            return False
        if self._process.poll() is None:
            return True
        return False


class RpcStructUris(BaseModel):
    status: Literal["used", "waiting"]
    uri: str


class RpcStructFiles(BaseModel):
    index: int
    path: str
    length: int
    completedLength: int
    selected: bool
    uris: List[RpcStructUris]


class RpcStructStatus(BaseModel):
    gid: str
    status: Literal["active", "waiting", "paused", "error", "complete", "removed"]
    totalLength: int
    completedLength: int
    downloadSpeed: int
    errorCode: Optional[str] = None
    errorMessage: Optional[str] = None
    dir: str


class RpcStructVersion(BaseModel):
    enabledFeatures: List[str]
    version: str


class RpcStructSessionInfo(BaseModel):
    sessionId: str


class RpcStructGlobalStat(BaseModel):
    downloadSpeed: int
    uploadSpeed: int
    numActive: int
    numWaiting: int
    numStopped: int
    numStoppedTotal: int


class Aria2Client:
    def __init__(self, server: str, token: str) -> None:
        self.token: str = f"token:{token}"
        self.rpc = f"{server}/jsonrpc"
        self.default_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0"

    def _make_rpcjson(self, method: str, params) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": "qwer",
            "method": method,
            "params": params,
        }

    def _post(self, data: dict):
        j: dict = requests.post(self.rpc, json.dumps(data).encode()).json()
        error = j.get("error")
        if error is not None:
            raise SyntaxError(f"\n#### Error: \nsend = {data} \nrecv = {j} \n####\n")
        result = j.get("result")
        if result is None:
            raise SyntaxError(f"\n#### NotResult: \nsend = {data} \nrecv = {j} \n####\n")
        return result

    def AddUri(
        self,
        url: str,
        savepath: str,
        filename: str,
        user_agent: str | None = None,
        proxy: str | None = None,
        ext_options: dict | None = None,
    ) -> str:
        options = {
            "dir": savepath,
            "out": filename,
            "user-agent": self.default_ua,
        }

        if user_agent is not None:
            options["user-agent"] = user_agent

        if proxy is not None:
            options["all-proxy"] = proxy

        if ext_options is not None:
            options.update(ext_options)

        data = self._make_rpcjson(
            "aria2.addUri",
            [self.token, [url], options],
        )

        result = self._post(data)

        if not isinstance(result, str):
            raise TypeError

        return result

    def _Gid_SuccReturnGid(self, method: str, gid: str) -> bool:
        data = self._make_rpcjson(
            method,
            [self.token, gid],
        )
        result = self._post(data)
        if not isinstance(result, str):
            return False
        if result == gid:
            return True
        return False

    def _Gid_ReturnOK(self, method: str, gid: str) -> bool:
        data = self._make_rpcjson(
            method,
            [self.token, gid],
        )
        result = self._post(data)
        if not isinstance(result, str):
            return False
        if result == "OK":
            return True
        return False

    def _All_ReturnOK(self, method: str) -> bool:
        data = self._make_rpcjson(
            method,
            [self.token],
        )
        result = self._post(data)
        if not isinstance(result, str):
            return False
        if result == "OK":
            return True
        return False

    def Remove(self, gid: str) -> bool:
        return self._Gid_SuccReturnGid("aria2.remove", gid)

    def ForceRemove(self, gid: str) -> bool:
        return self._Gid_SuccReturnGid("aria2.forceRemove", gid)

    def Pause(self, gid: str) -> bool:
        return self._Gid_SuccReturnGid("aria2.pause", gid)

    def PauseAll(self) -> bool:
        return self._All_ReturnOK("aria2.pauseAll")

    def ForcePause(self, gid: str) -> bool:
        return self._Gid_SuccReturnGid("aria2.forcePause", gid)

    def ForcePauseAll(self) -> bool:
        return self._All_ReturnOK("aria2.forcePauseAll")

    def Unpause(self, gid: str) -> bool:
        return self._Gid_SuccReturnGid("aria2.unpause", gid)

    def UnpauseAll(self) -> bool:
        return self._All_ReturnOK("aria2.unpauseAll")

    def TellStatus(self, gid: str):
        result = self._post(
            self._make_rpcjson(
                "aria2.tellStatus",
                [
                    self.token,
                    gid,
                    ["gid", "status", "totalLength", "completedLength", "downloadSpeed", "dir", "errorCode", "errorMessage"],
                ],
            )
        )
        return RpcStructStatus(**result)

    def GetFiles(self, gid: str):
        results = self._post(self._make_rpcjson("aria2.getFiles", [self.token, gid]))
        return [RpcStructFiles(**result) for result in results]

    def GetGlobalOption(self):
        result: Dict[str, str | int] = self._post(self._make_rpcjson("aria2.getGlobalOption", [self.token]))
        return result

    def GetGlobalStat(self):
        result = self._post(self._make_rpcjson("aria2.getGlobalStat", [self.token]))
        return RpcStructGlobalStat(**result)

    def PurgeDownloadResult(self) -> bool:
        return self._All_ReturnOK("aria2.purgeDownloadResult")

    def removeDownloadResult(self, gid: str) -> bool:
        try:
            self._Gid_ReturnOK("aria2.removeDownloadResult", gid)
            return True
        except Exception:
            return False

    def GetVersion(self):
        result = self._post(self._make_rpcjson("aria2.getVersion", [self.token]))
        return RpcStructVersion(**result)

    def GetSessionInfo(self):
        result = self._post(self._make_rpcjson("aria2.getSessionInfo", [self.token]))
        return RpcStructSessionInfo(**result)


def module_test():
    server = Aria2Server("./data/default_download", 20)
    client = Aria2Client("http://localhost:6800", "4XUjiltFc6dMQZmbo8g0Oui1pbvvNhbZ65PmYSBiQG3JuDcQvk39HQFPK8u9NhP1")

    server.Restart()

    print(f"{server.Cmd()}")
    print(f"aria2p --port={server.Port()} --secret={server.Token()}")

    try:
        # server.PrintStdout()

        gid = ""

        while True:
            match input("#="):
                case "add":
                    gid = client.AddUri(
                        url="https://mirrors.aliyun.com/kicad/windows/stable/kicad-9.0.5-x86_64.exe",
                        savepath="./test_path",
                        filename="test_name",
                        user_agent=None,
                        ext_options={"max-download-limit": "100K"},
                    )
                    r = gid
                case "remove":
                    r = client.Remove(gid)
                case "f-remove":
                    r = client.ForceRemove(gid)
                case "pause":
                    r = client.Pause(gid)
                case "pause-all":
                    r = client.PauseAll()
                case "f-pause":
                    r = client.ForcePause(gid)
                case "unpause":
                    r = client.Unpause(gid)
                case "unpause-all":
                    r = client.UnpauseAll()
                case "status":
                    r = client.TellStatus(gid)
                case "files":
                    r = client.GetFiles(gid)
                case "g-option":
                    r = client.GetGlobalOption()
                case "g-stat":
                    r = client.GetGlobalStat()
                case "purge-result":
                    r = client.PurgeDownloadResult()
                case "remove-result":
                    r = client.removeDownloadResult(gid)
                case "version":
                    r = client.GetVersion()
                case "session":
                    r = client.GetSessionInfo()
                case "set":
                    gid = input()
                    r = gid
                case _:
                    continue
            print(r)
            pass

    except Exception:
        server.Stop()
        raise Exception


if __name__ == "__main__":
    os.system("cls")
    os.system("chcp 65001")
    module_test()
