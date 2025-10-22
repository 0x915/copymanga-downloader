from pathlib import Path
from typing import List, Sequence, Tuple

import sqlalchemy
from sqlalchemy import inspect, types, select
from sqlalchemy.orm import Session, DeclarativeBase, Mapped, mapped_column

import spdlogger
from uuid import UUID

logger = spdlogger.logger


class _DeclarativeBase(DeclarativeBase):
    pass


class TableMetadata(_DeclarativeBase):
    __tablename__ = "metadata"
    index: Mapped[int] = mapped_column(types.INTEGER, primary_key=True)
    tag: Mapped[str] = mapped_column(types.TEXT)
    context: Mapped[str] = mapped_column(types.TEXT)
    status: Mapped[int] = mapped_column(types.INTEGER)

    @staticmethod
    def Create(
        tag: str,
        context: str,
        status: int,
    ):
        return TableMetadata(
            tag=tag,
            context=context,
            status=status,
        )


class TableChapters(_DeclarativeBase):
    __tablename__ = "chapters"
    # 自增索引 API索引   分组名 章节名 文件数 UUID   完成状态   其他状态
    index: Mapped[int] = mapped_column(types.INTEGER, primary_key=True)
    api_index: Mapped[int] = mapped_column(types.INTEGER)
    group: Mapped[str] = mapped_column(types.TEXT)
    name: Mapped[str] = mapped_column(types.TEXT)
    size: Mapped[int] = mapped_column(types.INTEGER)
    uuid: Mapped[UUID] = mapped_column(types.UUID)
    status: Mapped[int] = mapped_column(types.INTEGER)

    @staticmethod
    def Create(
        api_index: int,
        group: str,
        name: str,
        size: int,
        uuid: UUID,
        status: int,
    ):
        return TableChapters(
            api_index=api_index,
            group=group,
            name=name,
            size=size,
            uuid=uuid,
            status=status,
        )


class FileDlStatus:
    InvalidUrl = -255
    PathProblem = -1
    NewFile = 0
    Active = 1
    Completed = 255
    

class TableFiles(_DeclarativeBase):
    __tablename__ = "files"
    # 自增索引 API索引   分组名 章节名 页号 扩展名  储存位置 下载地址   跳过状态 下载状态   其他状态
    index: Mapped[int] = mapped_column(types.INTEGER, primary_key=True)
    api_index: Mapped[int] = mapped_column(types.INTEGER)
    group: Mapped[str] = mapped_column(types.TEXT)
    chapter: Mapped[str] = mapped_column(types.TEXT)
    page: Mapped[int] = mapped_column(types.TEXT)
    extension: Mapped[str] = mapped_column(types.TEXT)
    dl_path: Mapped[str] = mapped_column(types.TEXT)
    dl_url: Mapped[str] = mapped_column(types.TEXT)
    dl_skip: Mapped[bool] = mapped_column(types.BOOLEAN)
    dl_status: Mapped[int] = mapped_column(types.INTEGER)
    status: Mapped[int] = mapped_column(types.INTEGER)

    @staticmethod
    def Create(
        api_index: int,
        group: str,
        chapter: str,
        page: int,
        extension: str,
        dl_path: str,
        dl_url: str,
        dl_skip: bool,
        dl_status: int,
        status: int,
    ):
        return TableFiles(
            api_index=api_index,
            group=group,
            chapter=chapter,
            page=page,
            extension=extension,
            dl_path=dl_path,
            dl_url=dl_url,
            dl_skip=dl_skip,
            dl_status=dl_status,
            status=status,
        )


class SqliteClient:
    #
    def __init__(self, filepath: Path):
        self._logger = logger.ObjLogger(self)
        self._filepath: Path = filepath
        self._filepath.resolve().parent.mkdir(parents=True, exist_ok=True)
        self.engine: sqlalchemy.Engine = sqlalchemy.create_engine(
            f"sqlite:///{self._filepath.as_posix()}",
        )
        if not (
            inspect(self.engine).has_table("metadata")  #
            and inspect(self.engine).has_table("chapters")
            and inspect(self.engine).has_table("files")
        ):
            _DeclarativeBase.metadata.create_all(self.engine)
        return

    def GetFilePath(self):
        return self._filepath.resolve()
