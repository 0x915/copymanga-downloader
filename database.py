from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import sqlalchemy
from sqlalchemy import Engine, inspect, types, select
from sqlalchemy.orm import Session, DeclarativeBase, Mapped, mapped_column
from multipledispatch import dispatch

import spdlogger
from uuid import UUID
import threading

uuid0 = UUID("00000000-0000-0000-0000-000000000000")

logger = spdlogger.logger


class _ComicTableBase(DeclarativeBase):
    pass


class MetadataOptional:
    def __init__(
        self,
        tag: Optional[str] = None,
        name: Optional[str] = None,
        value: Optional[str] = None,
        status: Optional[int] = None,
        index: Optional[int] = None,
    ) -> None:
        self.index = index
        self.tag = tag
        self.name = name
        self.value = value
        self.status = status


class Metadata:
    def __init__(
        self,
        tag: str,
        name: str,
        value: str,
        status: int,
        index: int,
    ) -> None:
        self.index: int = index
        self.tag: str = tag
        self.name: str = name
        self.value: str = value
        self.status: int = status


class MetadataORM(_ComicTableBase):
    __tablename__ = "metadata"
    index: Mapped[int] = mapped_column(types.INTEGER, primary_key=True)
    tag: Mapped[str] = mapped_column(types.TEXT)
    name: Mapped[str] = mapped_column(types.TEXT)
    value: Mapped[str] = mapped_column(types.TEXT)
    status: Mapped[int] = mapped_column(types.INTEGER)

    def __str__(self) -> str:
        return f"<{self.__tablename__} [{self.index}]{self.tag, self.name, self.value, self.status} />"

    def __repr__(self) -> str:
        return self.__str__()

    @staticmethod
    def Create(
        tag: Optional[str] = None,
        name: Optional[str] = None,
        value: Optional[str] = None,
        status: Optional[int] = None,
    ):
        return MetadataORM(
            tag="" if tag is None else tag,
            name="" if name is None else name,
            value="" if value is None else value,
            status=0 if status is None else status,
        )

    @staticmethod
    def From(struct: MetadataOptional | Metadata):
        return MetadataORM.Create(
            tag=struct.tag,
            name=struct.name,
            value=struct.value,
            status=struct.status,
        )

    def Set(self, struct: MetadataOptional | Metadata):
        if struct.tag is not None:
            self.tag = struct.tag
        if struct.name is not None:
            self.name = struct.name
        if struct.value is not None:
            self.value = struct.value
        if struct.status is not None:
            self.status = struct.status
        return

    @staticmethod
    def MakeQuery(session: Session, struct: MetadataOptional | Metadata):
        query = session.query(MetadataORM)
        if struct.index is not None:
            query = query.filter_by(index=struct.index)
        if struct.tag is not None:
            query = query.filter_by(tag=struct.tag)
        if struct.name is not None:
            query = query.filter_by(name=struct.name)
        if struct.value is not None:
            query = query.filter_by(value=struct.value)
        if struct.status is not None:
            query = query.filter_by(status=struct.status)
        return query


#
#
#


class ChapterOptional:
    def __init__(
        self,
        api_index: Optional[int] = None,
        group: Optional[str] = None,
        name: Optional[str] = None,
        size: Optional[int] = None,
        uuid: Optional[UUID] = None,
        status: Optional[int] = None,
        index: Optional[int] = None,
    ) -> None:
        self.index = index
        self.api_index = api_index
        self.group = group
        self.name = name
        self.size = size
        self.uuid = uuid
        self.status = status


class Chapter:
    def __init__(
        self,
        api_index: int,
        group: str,
        name: str,
        size: int,
        uuid: UUID,
        status: int,
        index: int,
    ) -> None:
        self.index = index
        self.api_index = api_index
        self.group = group
        self.name = name
        self.size = size
        self.uuid = uuid
        self.status = status


class ChapterORM(_ComicTableBase):
    __tablename__ = "chapters"
    # 自增索引 API索引   分组名 章节名 文件数 UUID   完成状态   其他状态
    index: Mapped[int] = mapped_column(types.INTEGER, primary_key=True)
    api_index: Mapped[int] = mapped_column(types.INTEGER)
    group: Mapped[str] = mapped_column(types.TEXT)
    name: Mapped[str] = mapped_column(types.TEXT)
    size: Mapped[int] = mapped_column(types.INTEGER)
    uuid: Mapped[UUID] = mapped_column(types.UUID)
    status: Mapped[int] = mapped_column(types.INTEGER)

    def __str__(self) -> str:
        return f"<{self.__tablename__} [{self.index}]{self.api_index, self.group, self.name, self.size, self.uuid, self.status} />"

    def __repr__(self) -> str:
        return self.__str__()

    @staticmethod
    def Create(
        api_index: Optional[int] = None,
        group: Optional[str] = None,
        name: Optional[str] = None,
        size: Optional[int] = None,
        uuid: Optional[UUID] = None,
        status: Optional[int] = None,
    ):
        return ChapterORM(
            api_index=-1 if api_index is None else api_index,
            group="" if group is None else group,
            name="" if name is None else name,
            size=0 if size is None else size,
            uuid=uuid0 if uuid is None else uuid,
            status=0 if status is None else status,
        )

    def Set(self, struct: ChapterOptional | Chapter):
        if struct.api_index is not None:
            self.api_index = struct.api_index
        if struct.group is not None:
            self.group = struct.group
        if struct.name is not None:
            self.name = struct.name
        if struct.size is not None:
            self.size = struct.size
        if struct.uuid is not None:
            self.uuid = struct.uuid
        if struct.status is not None:
            self.status = struct.status
        return

    @staticmethod
    def From(struct: ChapterOptional | Chapter):
        return ChapterORM.Create(
            api_index=struct.api_index,
            group=struct.group,
            name=struct.name,
            size=struct.size,
            uuid=struct.uuid,
            status=struct.status,
        )

    @staticmethod
    def MakeQuery(session: Session, struct: ChapterOptional | Chapter):
        query = session.query(ChapterORM)
        if struct.index is not None:
            query = query.filter_by(index=struct.index)
        if struct.api_index is not None:
            query = query.filter_by(api_index=struct.api_index)
        if struct.group is not None:
            query = query.filter_by(group=struct.group)
        if struct.name is not None:
            query = query.filter_by(name=struct.name)
        if struct.size is not None:
            query = query.filter_by(size=struct.size)
        if struct.uuid is not None:
            query = query.filter_by(uuid=struct.uuid)
        if struct.status is not None:
            query = query.filter_by(status=struct.status)
        return query


#
#
#


class FileOptional:
    def __init__(
        self,
        api_index: Optional[int] = None,
        group: Optional[str] = None,
        chapter: Optional[str] = None,
        page: Optional[int] = None,
        extension: Optional[str] = None,
        dl_path: Optional[str] = None,
        dl_url: Optional[str] = None,
        dl_skip: Optional[bool] = None,
        dl_status: Optional[int] = None,
        status: Optional[int] = None,
        index: Optional[int] = None,
    ) -> None:
        self.index = index
        self.api_index = api_index
        self.group = group
        self.chapter = chapter
        self.page = page
        self.extension = extension
        self.dl_path = dl_path
        self.dl_url = dl_url
        self.dl_skip = dl_skip
        self.dl_status = dl_status
        self.status = status


class File:
    class DlStatus:
        InvalidUrl = -255
        Error = -1
        Wait = 0
        Active = 1
        Update = 254
        Completed = 255

    def __init__(
        self,
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
        index: int,
    ) -> None:
        self.index = index
        self.api_index = api_index
        self.group = group
        self.chapter = chapter
        self.page = page
        self.extension = extension
        self.dl_path = dl_path
        self.dl_url = dl_url
        self.dl_skip = dl_skip
        self.dl_status = dl_status
        self.status = status


class FileORM(_ComicTableBase):
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

    def __str__(self) -> str:
        return f"<{self.__tablename__} [{self.index}]{
            (
                self.api_index,
                self.group,
                self.chapter,
                self.page,
                self.extension,
                self.dl_path,
                self.dl_url,
                self.dl_skip,
                self.dl_status,
                self.status,
            )
        } />"

    def __repr__(self) -> str:
        return self.__str__()

    @staticmethod
    def Create(
        api_index: Optional[int] = None,
        group: Optional[str] = None,
        chapter: Optional[str] = None,
        page: Optional[int] = None,
        extension: Optional[str] = None,
        dl_path: Optional[str] = None,
        dl_url: Optional[str] = None,
        dl_skip: Optional[bool] = None,
        dl_status: Optional[int] = None,
        status: Optional[int] = None,
    ):
        return FileORM(
            api_index=-1 if api_index is None else api_index,
            group="" if group is None else group,
            chapter="" if chapter is None else chapter,
            page=-1 if page is None else page,
            extension="" if extension is None else extension,
            dl_path="" if dl_path is None else dl_path,
            dl_url="" if dl_url is None else dl_url,
            dl_skip=False if dl_skip is None else dl_skip,
            dl_status=0 if dl_status is None else dl_status,
            status=0 if status is None else status,
        )

    def Set(self, struct: FileOptional | File):
        if struct.api_index is not None:
            self.api_index = struct.api_index
        if struct.group is not None:
            self.group = struct.group
        if struct.chapter is not None:
            self.chapter = struct.chapter
        if struct.page is not None:
            self.page = struct.page
        if struct.extension is not None:
            self.extension = struct.extension
        if struct.dl_path is not None:
            self.dl_path = struct.dl_path
        if struct.dl_url is not None:
            self.dl_url = struct.dl_url
        if struct.dl_skip is not None:
            self.dl_skip = struct.dl_skip
        if struct.dl_status is not None:
            self.dl_status = struct.dl_status
        if struct.status is not None:
            self.status = struct.status
        return

    @staticmethod
    def From(struct: FileOptional | File):
        return FileORM.Create(
            api_index=struct.api_index,
            group=struct.group,
            chapter=struct.chapter,
            page=struct.page,
            extension=struct.extension,
            dl_path=struct.dl_path,
            dl_url=struct.dl_url,
            dl_skip=struct.dl_skip,
            dl_status=struct.dl_status,
            status=struct.status,
        )

    @staticmethod
    def MakeQuery(session: Session, struct: FileOptional | File):
        query = session.query(FileORM)
        if struct.index is not None:
            query = query.filter_by(index=struct.index)
        if struct.api_index is not None:
            query = query.filter_by(api_index=struct.api_index)
        if struct.group is not None:
            query = query.filter_by(group=struct.group)
        if struct.chapter is not None:
            query = query.filter_by(chapter=struct.chapter)
        if struct.page is not None:
            query = query.filter_by(page=struct.page)
        if struct.extension is not None:
            query = query.filter_by(extension=struct.extension)
        if struct.dl_path is not None:
            query = query.filter_by(dl_path=struct.dl_path)
        if struct.dl_url is not None:
            query = query.filter_by(dl_url=struct.dl_url)
        if struct.dl_skip is not None:
            query = query.filter_by(dl_skip=struct.dl_skip)
        if struct.dl_status is not None:
            query = query.filter_by(dl_status=struct.dl_status)
        if struct.status is not None:
            query = query.filter_by(status=struct.status)
        return query


class ComicDatabase:
    def __init__(self, filepath: Path):
        self._logger = logger.ObjLogger(self)
        self._filepath: Path = filepath
        self._filepath.resolve().parent.mkdir(parents=True, exist_ok=True)
        self.engine: sqlalchemy.Engine = sqlalchemy.create_engine(
            f"sqlite:///{self._filepath.as_posix()}",
        )

        _ComicTableBase.metadata.create_all(self.engine)

        self.lock = threading.Lock()
        self.session = Session(self.engine)

        self.attribute = ComicDatabase._Attribute(self.session)
        self.group = ComicDatabase._Group(self.session)
        self.chapter = ComicDatabase._Chapter(self.session)
        self.file = ComicDatabase._File(self.session)

        return

    def Delete(self, obj: FileORM | ChapterORM | MetadataORM):
        self.session.delete(obj)
        self.session.commit()

    def Commit(self):
        self.session.commit()

    def GetDatabaseFilePath(self) -> Path:
        return self._filepath.resolve()

    class _Attribute:
        #
        METADATA_NAME_TAG = "__name__"

        def __init__(self, session: Session) -> None:
            self.session = session

        def __getitem__(self, tag: str):
            return self.ForceTagGet(tag)

        def __setitem__(self, tag: str, struct: MetadataOptional):
            self.ForceTagSet(tag, struct)

        def SelectTag(self, tag: str):
            return MetadataORM.MakeQuery(
                self.session,
                MetadataOptional(tag=tag),
            ).first()

        def ForceTagGet(self, tag: str):
            return MetadataORM.MakeQuery(
                self.session,
                MetadataOptional(tag=tag),
            ).one()

        def AddTag(self, tag: str, struct: MetadataOptional):
            if self.SelectTag(tag) is not None:
                raise ValueError(f"重复插入属性 tag={tag} 已存在")
            struct.tag = tag
            item = MetadataORM.From(struct)
            self.session.add(item)
            self.session.commit()
            return item

        def ForceTagSet(self, tag: str, struct: MetadataOptional):
            item = self.ForceTagGet(tag)
            struct.tag = None
            item.Set(struct)
            self.session.commit()
            return item

        def GetName(self):
            check = self.ForceTagGet(self.METADATA_NAME_TAG).name
            if len(check) != 0:
                return check
            raise ValueError(f"名称为空 {self.ForceTagGet(self.METADATA_NAME_TAG)}")

        def SetName(self, name: str):
            return self.ForceTagSet(self.METADATA_NAME_TAG, MetadataOptional(name=name))

        def GetPathword(self):
            check = self.ForceTagGet(self.METADATA_NAME_TAG).value
            if len(check) != 0:
                return check
            check = self.SelectTag("__pathword__")
            if check is not None and len(check.name) != 0:
                self.SetPathword(check.name)
                return check.name
            raise ValueError(f"路径词为空 {self.ForceTagGet(self.METADATA_NAME_TAG)}")

        def SetPathword(self, pathword: str):
            return self.ForceTagSet(self.METADATA_NAME_TAG, MetadataOptional(value=pathword))

    class _Group:
        #
        METADATA_GROUP_TAG = "__group__"

        def __init__(self, session: Session) -> None:
            self.session = session

        def __getitem__(self, name: str):
            return self.ForceNameGet(name)

        def __setitem__(self, name: str, struct: MetadataOptional):
            self.ForceNameSet(name, struct)

        # ================================================================================================

        def GetAll(self, struct: Optional[MetadataOptional] = None):
            _struct = MetadataOptional() if struct is None else struct
            _struct.tag = self.METADATA_GROUP_TAG
            return MetadataORM.MakeQuery(self.session, _struct).all()

        def GetFirst(self, struct: MetadataOptional):
            struct.tag = self.METADATA_GROUP_TAG
            return MetadataORM.MakeQuery(self.session, struct).first()

        def GetOne(self, struct: MetadataOptional):
            struct.tag = self.METADATA_GROUP_TAG
            return MetadataORM.MakeQuery(self.session, struct).one()

        # ================================================================================================

        def SelectName(self, name: str):
            return self.GetFirst(MetadataOptional(name=name))

        def ForceNameGet(self, name: str):
            return self.GetOne(MetadataOptional(name=name))

        def AddName(self, name: str, pathword: str):
            if self.SelectName(name):
                raise ValueError(f"重复插入分组 name={name} 已存在")
            item = MetadataORM.Create(tag=self.METADATA_GROUP_TAG, name=name, value=pathword)
            self.session.add(item)
            self.session.commit()
            return item

        def ForceNameSet(self, name: str, struct: MetadataOptional):
            item = self.ForceNameGet(name)
            struct.tag = None
            struct.name = None
            item.Set(struct)
            self.session.commit()
            return item

    class _Chapter:
        #
        def __init__(self, session: Session) -> None:
            self.session = session

        def __getitem__(self, index: int):
            return self.ForceIndexGet(index)

        def __setitem__(self, index: int, struct: ChapterOptional):
            self.ForceIndexSet(index, struct)

        # ================================================================================================

        def GetAll(self, struct: ChapterOptional):
            return ChapterORM.MakeQuery(self.session, struct).all()

        def GetFirst(self, struct: ChapterOptional):
            return ChapterORM.MakeQuery(self.session, struct).first()

        def GetOne(self, struct: ChapterOptional):
            return ChapterORM.MakeQuery(self.session, struct).one()

        # ================================================================================================

        def SelectName(self, group: str, name: str):
            return self.GetFirst(ChapterOptional(group=group, name=name))

        def SelectIndex(self, index: int):
            return self.GetFirst(ChapterOptional(index=index))

        def SelectUUID(self, uuid: UUID):
            return self.GetFirst(ChapterOptional(uuid=uuid))

        def ForceIndexGet(self, index: int):
            return self.GetOne(ChapterOptional(index=index))

        def ForceGroupGet(self, group: str):
            return self.GetAll(ChapterOptional(group=group))

        def ForceNameGet(self, group: str, name: str):
            return self.GetOne(ChapterOptional(group=group, name=name))

        def ForceIndexSet(self, index: int, struct: ChapterOptional):
            item = self.ForceIndexGet(index)
            struct.group = None
            struct.name = None
            item.Set(struct)
            self.session.commit()
            return item

        def ForceNameSet(self, group: str, name: str, struct: ChapterOptional):
            item = self.ForceNameGet(group, name)
            struct.group = None
            struct.name = None
            item.Set(struct)
            self.session.commit()
            return item

        def AddName(self, group: str, name: str, struct: ChapterOptional):
            if self.SelectName(group, name):
                raise ValueError(f"重复插入章节 group={group} name={name} 已存在")
            struct.group = group
            struct.name = name
            item = ChapterORM.From(struct)
            self.session.add(item)
            self.session.commit()
            return item

    class _File:
        #
        def __init__(self, session: Session) -> None:
            self.session = session

        def __getitem__(self, index: int):
            return self.ForceIndexGet(index)

        def __setitem__(self, index: int, struct: FileOptional):
            self.ForceIndexSet(index, struct)

        # ================================================================================================

        def GetAll(self, struct: FileOptional):
            return FileORM.MakeQuery(self.session, struct).all()

        def GetFirst(self, struct: FileOptional):
            return FileORM.MakeQuery(self.session, struct).first()

        def GetOne(self, struct: FileOptional):
            return FileORM.MakeQuery(self.session, struct).one()

        # ================================================================================================

        def SelectPage(self, group: str, chapter: str, page: int):
            return self.GetFirst(FileOptional(group=group, chapter=chapter, page=page))

        def SelectIndex(self, index: int):
            return self.GetFirst(FileOptional(index=index))

        def ForceIndexGet(self, index: int):
            return self.GetOne(FileOptional(index=index))

        def ForceChapterGet(self, group: str, chapter: str):
            return self.GetAll(FileOptional(group=group, chapter=chapter))

        def ForcePageGet(self, group: str, chapter: str, page: int):
            return self.GetOne(FileOptional(group=group, chapter=chapter, page=page))

        def ForceIndexSet(self, index: int, struct: FileOptional):
            item = self.ForceIndexGet(index)
            struct.group = None
            struct.chapter = None
            struct.page = None
            item.Set(struct)
            self.session.commit()
            return item

        def ForcePageSet(self, group: str, chapter: str, page: int, struct: FileOptional):
            item = self.ForcePageGet(group, chapter, page)
            struct.group = None
            struct.chapter = None
            struct.page = None
            item.Set(struct)
            self.session.commit()
            return item

        def AddPage(self, group: str, chapter: str, page: int, struct: FileOptional):
            if self.SelectPage(group, chapter, page):
                raise ValueError(f"重复插入文件 group={group} chapter={chapter} page={page} 已存在")
            struct.group = group
            struct.chapter = chapter
            struct.page = page
            item = FileORM.From(struct)
            self.session.add(item)
            self.session.commit()
            return item

        # ================================================================================================

        def Set_DlStatus_Wait(self, index: int):
            self.ForceIndexSet(index, FileOptional(dl_status=File.DlStatus.Wait))

        def Set_DlStatus_Active(self, index: int):
            self.ForceIndexSet(index, FileOptional(dl_status=File.DlStatus.Active))

        def Set_DlStatus_Error(self, index: int):
            self.ForceIndexSet(index, FileOptional(dl_status=File.DlStatus.Error))

        def Set_DlStatus_Completed(self, index: int):
            self.ForceIndexSet(index, FileOptional(dl_status=File.DlStatus.Completed))

        def All_Wait_DlStatus(self):
            return self.GetAll(FileOptional(dl_status=File.DlStatus.Wait))

        def All_Active_DlStatus(self):
            return self.GetAll(FileOptional(dl_status=File.DlStatus.Active))

        def All_Error_DlStatus(self):
            return self.GetAll(FileOptional(dl_status=File.DlStatus.Error))

        def All_Completed_DlStatus(self):
            return self.GetAll(FileOptional(dl_status=File.DlStatus.Completed))

        def First_Wait_DlStatus(self):
            return self.GetFirst(FileOptional(dl_status=File.DlStatus.Wait))

        def First_Active_DlStatus(self):
            return self.GetFirst(FileOptional(dl_status=File.DlStatus.Active))

        def First_Error_DlStatus(self):
            return self.GetFirst(FileOptional(dl_status=File.DlStatus.Error))

        def First_Completed_DlStatus(self):
            return self.GetFirst(FileOptional(dl_status=File.DlStatus.Completed))


def module_test():
    from pprint import pprint

    db = ComicDatabase(Path(f"db.nosync/silentwitchchenmodemonvdemimi.db"))

    name = db.attribute.GetName()
    print("raw = ", name)
    db.attribute.SetName("-Silent Witch-沉默的魔女的秘密")
    print("new = ", db.attribute.GetName())

    pathword = db.attribute.GetPathword()
    print("raw = ", pathword)
    db.attribute.SetPathword("silentwitchchenmodemonvdemimi")
    print("new = ", db.attribute.GetPathword())

    groups = db.group.GetAll()
    pprint(groups)
    chapters = db.chapter.ForceGroupGet(groups[0].name)
    pprint(chapters)
    files = db.file.ForceChapterGet(groups[0].name, chapters[0].name)
    pprint(files)

    pass


if __name__ == "__main__":
    module_test()
