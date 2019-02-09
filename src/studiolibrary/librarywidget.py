# Copyright 2017 by Kurt Rathjen. All Rights Reserved.
#
# This library is free software: you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation, either
# version 3 of the License, or (at your option) any later version.
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# Lesser General Public License for more details.
# You should have received a copy of the GNU Lesser General Public
# License along with this library. If not, see <http://www.gnu.org/licenses/>.

import re
import os
import time
import copy
import logging
from functools import partial

from studioqt import QtGui
from studioqt import QtCore
from studioqt import QtWidgets

import studioqt
import studiolibrary


__all__ = ["LibraryWidget"]


logger = logging.getLogger(__name__)


class PreviewFrame(QtWidgets.QFrame):
    pass


class SidebarFrame(QtWidgets.QFrame):
    pass


class GlobalSignal(QtCore.QObject):
    """
    Triggered for all library instance.
    """
    debugModeChanged = QtCore.Signal(object, object)
    folderSelectionChanged = QtCore.Signal(object, object)


class LibraryWidget(QtWidgets.QWidget):

    _instances = {}

    DEFAULT_NAME = "Default"
    DEFAULT_SETTINGS = {
        "paneSizes": [160, 280, 180],
        "geometry": [-1, -1, 860, 720],
        "trashFolderVisible": False,
        "sidebarWidgetVisible": True,
        "previewWidgetVisible": True,
        "menuBarWidgetVisible": True,
        "statusBarWidgetVisible": True,
        "recursiveSearchEnabled": False,
        "itemsWidget": {
                "spacing": 2,
                "padding": 6,
                "sortOrder": 0,
                "sortColumn": "Custom Order",
                "groupOrder": 0,
                "groupColumn": "Category",
                "zoomAmount": 80,
                "textVisible": True,
            },
        "searchWidget": {
                "text": "",
            },
        "theme": {
                "accentColor": "rgb(0, 175, 240, 255)",
                "backgroundColor": "rgb(60, 64, 79, 255)",
            }
        }

    SETTINGS_PATH = "{local}/StudioLibrary/LibraryWidget.json"

    TRASH_ENABLED = True

    RECURSIVE_SEARCH_ENABLED = False

    # Still in development
    DPI_ENABLED = False
    DPI_MIN_VALUE = 80
    DPI_MAX_VALUE = 250

    globalSignal = GlobalSignal()

    # Local signal
    loaded = QtCore.Signal()
    lockChanged = QtCore.Signal(object)
    debugModeChanged = QtCore.Signal(object)

    itemRenamed = QtCore.Signal(str, str)
    itemSelectionChanged = QtCore.Signal(object)

    folderRenamed = QtCore.Signal(str, str)
    folderSelectionChanged = QtCore.Signal(object)

    @staticmethod
    def instances():
        """
        Return all the LibraryWidget instances that have been initialised.

        :rtype: list[LibraryWidget]
        """
        return LibraryWidget._instances.values()

    @staticmethod
    def destroyInstances():
        """Delete all library widget instances."""
        for widget in LibraryWidget.instances():
            widget.hide()
            widget.close()

        LibraryWidget._instances = []

    @classmethod
    def instance(
            cls,
            name="",
            path="",
            show=True,
            lock=False,
            superusers=None,
            lockRegExp=None,
            unlockRegExp=None,
            **kwargs
    ):
        """
        Return the library widget for the given name.

        :type name: str
        :type path: str
        :type show: bool
        :type lock: bool
        :type superusers: list[str]
        :type lockRegExp: str
        :type unlockRegExp: str
        
        :rtype: LibraryWidget
        """
        name = name or cls.DEFAULT_NAME

        libraryWidget = LibraryWidget._instances.get(name)

        if not libraryWidget:
            libraryWidget = cls(name=name)
            LibraryWidget._instances[name] = libraryWidget

        libraryWidget.setLocked(lock)
        libraryWidget.setSuperusers(superusers)
        libraryWidget.setLockRegExp(lockRegExp)
        libraryWidget.setUnlockRegExp(unlockRegExp)

        if path:
            libraryWidget.setPath(path)

        if show:
            libraryWidget.show(**kwargs)

        return libraryWidget

    def __init__(self, parent=None, name="", path=""):
        """
        Create a new instance of the Library Widget.

        :type parent: QtWidgets.QWidget or None
        :type name: str
        :type path: str
        """
        QtWidgets.QWidget.__init__(self, parent)

        self.setObjectName("studiolibrary")

        version = studiolibrary.version()
        studiolibrary.sendAnalytics("MainWindow", version=version)

        resource = studiolibrary.resource()
        self.setWindowIcon(resource.icon("icon_black"))

        self._dpi = 1.0
        self._path = ""
        self._items = []
        self._name = name or self.DEFAULT_NAME
        self._theme = None
        self._isDebug = False
        self._isLocked = False
        self._isLoaded = False
        self._previewWidget = None
        self._currentItem = None
        self._library = None
        self._refreshEnabled = False

        self._superusers = None
        self._lockRegExp = None
        self._unlockRegExp = None

        self._trashEnabled = self.TRASH_ENABLED
        self._recursiveSearchEnabled = self.RECURSIVE_SEARCH_ENABLED

        self._itemsHiddenCount = 0
        self._itemsVisibleCount = 0

        self._isTrashFolderVisible = False
        self._sidebarWidgetVisible = True
        self._previewWidgetVisible = True
        self._statusBarWidgetVisible = True

        # --------------------------------------------------------------------
        # Create Widgets
        # --------------------------------------------------------------------

        self._sidebarFrame = SidebarFrame(self)
        self._previewFrame = PreviewFrame(self)

        self._itemsWidget = studioqt.ItemsWidget(self)

        tip = "Search all current items."
        self._searchWidget = studioqt.SearchWidget(self)
        self._searchWidget.setToolTip(tip)
        self._searchWidget.setStatusTip(tip)

        self._statusWidget = studioqt.StatusWidget(self)
        self._menuBarWidget = studioqt.MenuBarWidget()
        self._sidebarWidget = studioqt.SidebarWidget(self)

        self.setMinimumWidth(5)
        self.setMinimumHeight(5)

        # --------------------------------------------------------------------
        # Setup the menu bar buttons
        # --------------------------------------------------------------------

        name = "New Item"
        icon = studioqt.resource.icon("add")
        tip = "Add a new item to the selected folder"
        self.addMenuBarAction(name, icon, tip, callback=self.showNewMenu)

        self._menuBarWidget.addWidget(self._searchWidget)

        name = "Item View"
        icon = studioqt.resource.icon("view_settings")
        tip = "Change the style of the item view"
        self.addMenuBarAction(name, icon, tip, callback=self.showItemViewMenu)

        name = "Group By"
        icon = studioqt.resource.icon("groupby")
        tip = "Group the current items in the view by column"
        self.addMenuBarAction(name, icon, tip, callback=self.showGroupByMenu)

        name = "Sort By"
        icon = studioqt.resource.icon("sortby")
        tip = "Sort the current items in the view by column"
        self.addMenuBarAction(name, icon, tip, callback=self.showSortByMenu)

        name = "View"
        icon = studioqt.resource.icon("view")
        tip = "Choose to show/hide both the preview and navigation pane. " \
              "Click + CTRL will hide the menu bar as well."
        self.addMenuBarAction(name, icon, tip, callback=self.toggleView)

        name = "Sync items"
        icon = studioqt.resource.icon("sync")
        tip = "Sync with the filesystem"
        self.addMenuBarAction(name, icon, tip, callback=self.sync)

        name = "Settings"
        icon = studioqt.resource.icon("settings")
        tip = "Settings menu"
        self.addMenuBarAction(name, icon, tip, callback=self.showSettingsMenu)

        # -------------------------------------------------------------------
        # Setup Layout
        # -------------------------------------------------------------------

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 1, 0, 0)
        self._previewFrame.setLayout(layout)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 1, 0, 0)

        self._sidebarFrame.setLayout(layout)
        self._sidebarFrame.layout().addWidget(self._sidebarWidget)

        self._splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal, self)
        self._splitter.setSizePolicy(QtWidgets.QSizePolicy.Ignored,
                                     QtWidgets.QSizePolicy.Expanding)
        self._splitter.setHandleWidth(2)
        self._splitter.setChildrenCollapsible(False)

        self._splitter.insertWidget(0, self._sidebarFrame)
        self._splitter.insertWidget(1, self._itemsWidget)
        self._splitter.insertWidget(2, self._previewFrame)

        self._splitter.setStretchFactor(0, False)
        self._splitter.setStretchFactor(1, True)
        self._splitter.setStretchFactor(2, False)

        self.layout().addWidget(self._menuBarWidget)
        self.layout().addWidget(self._splitter)
        self.layout().addWidget(self._statusWidget)

        vbox = QtWidgets.QVBoxLayout()
        self._previewFrame.setLayout(vbox)
        self._previewFrame.layout().setSpacing(0)
        self._previewFrame.layout().setContentsMargins(0, 0, 0, 0)
        self._previewFrame.setMinimumWidth(5)

        # -------------------------------------------------------------------
        # Setup Connections
        # -------------------------------------------------------------------

        searchWidget = self.searchWidget()
        searchWidget.searchChanged.connect(self._searchChanged)

        itemsWidget = self.itemsWidget()
        itemsWidget.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        itemsWidget.itemMoved.connect(self._itemMoved)
        itemsWidget.itemDropped.connect(self._itemDropped)
        itemsWidget.itemSelectionChanged.connect(self._itemSelectionChanged)
        itemsWidget.customContextMenuRequested.connect(self.showItemsContextMenu)

        sidebarWidget = self.sidebarWidget()
        sidebarWidget.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        sidebarWidget.itemDropped.connect(self._itemDropped)
        sidebarWidget.itemSelectionChanged.connect(self._folderSelectionChanged)
        sidebarWidget.customContextMenuRequested.connect(self.showFolderMenu)

        self.folderSelectionChanged.connect(self.updateLock)

        self.updateViewButton()

        if path:
            self.setPath(path)

    def _searchChanged(self):
        """
        Triggered when the search text has changed.

        :rtype: None
        """
        self.refreshItems()

    def _itemMoved(self, item):
        """
        Triggered when the custom order has changed.

        :type item: studiolibrary.LibraryItem
        :rtype: None
        """
        self.saveCustomOrder()

    def _itemSelectionChanged(self):
        """
        Triggered when an item is selected or deselected.

        :rtype: None
        """
        item = self.itemsWidget().selectedItem()

        self.setPreviewWidgetFromItem(item)
        self.itemSelectionChanged.emit(item)

    def _itemDropped(self, event):
        """
        Triggered when items are dropped on the items widget or sidebar widget.

        :type event: QtCore.QEvent
        :rtype: None
        """
        mimeData = event.mimeData()

        if mimeData.hasUrls():
            urls = mimeData.urls()
            path = self.selectedFolderPath()
            items = self.createItemsFromUrls(urls)

            if self.isMoveItemsEnabled():
                self.showMoveItemsDialog(items, dst=path)

            elif not self.isCustomOrderEnabled():
                msg = 'Please sort by "Custom Order" to reorder items!'
                self.showInfoMessage(msg)

    def _folderSelectionChanged(self):
        """
        Triggered when a folder is selected or deselected.

        :rtype: None
        """
        path = self.selectedFolderPath()
        self.refreshItems()

        self.folderSelectionChanged.emit(path)
        self.globalSignal.folderSelectionChanged.emit(self, path)

    def createLibrary(self):
        """
        Create a new library model instance.
        
        :rtype: studiolibrary.Library 
        """
        path = self.path()

        library = studiolibrary.Library(path)
        library.dataChanged.connect(self.refresh)

        return library

    def library(self):
        """
        Return the library model object.

        :rtype: studiolibrary.Library
        """
        return self._library

    def setLibrary(self, library):
        """
        Set the library model.

        :type library: studiolibrary.Library
        :rtype: None
        """
        self._library = library
        self.itemsWidget().setSortLabels(library.SortLabels)
        self.itemsWidget().setGroupLabels(library.GroupLabels)
        self.itemsWidget().setColumnLabels(library.ColumnLabels)

    def statusWidget(self):
        """
        Return the status widget.
        
        :rtype: studioqt.StatusWidget
        """
        return self._statusWidget

    def searchWidget(self):
        """
        Return the search widget.
        
        :rtype: studioqt.SearchWidget
        """
        return self._searchWidget

    def menuBarWidget(self):
        """
        Return the menu bar widget.
        
        :rtype: MenuBarWidget
        """
        return self._menuBarWidget

    def name(self):
        """
        Return the name of the library.

        :rtype: str
        """
        return self._name

    def path(self):
        """
        Return the root path for the library.

        :rtype: str
        """
        return self._path

    def setPath(self, path):
        """
        Set the root path for the library.

        :type path: str
        :rtype: None
        """
        path = studiolibrary.realPath(path)

        if path == self.path():
            logger.debug("The root path is already set.")
            return

        self._path = path

        library = self.createLibrary()
        self.setLibrary(library)

        self.refresh()

    @studioqt.showArrowCursor
    def showPathErrorDialog(self):
        """
        Called when the current root path doesn't exist on refresh.

        :rtype: None
        """
        path = self.path()

        title = "Path Error"

        text = 'The current root path does not exist "{path}". ' \
               'Please select a new root path to continue.'

        text = text.format(path=path)

        dialog = studioqt.createMessageBox(self, title, text)

        dialog.setHeaderColor("rgb(230, 80, 80)")
        dialog.show()

        dialog.accepted.connect(self.showChangePathDialog)

    @studioqt.showArrowCursor
    def showWelcomeDialog(self):
        """
        Called when there is no root path set for the library.

        :rtype: None
        """
        name = self.name()

        title = "Welcome"
        title = title.format(studiolibrary.version(), name)

        text = "Before you get started please choose a folder " \
               "location for storing the data. A network folder is " \
               "recommended for sharing within a studio."

        dialog = studioqt.createMessageBox(self, title, text)
        dialog.show()

        dialog.accepted.connect(self.showChangePathDialog)

    def showChangePathDialog(self):
        """
        Show a file browser dialog for changing the root path.

        :rtype: None
        """
        path = self._showChangePathDialog()
        if path:
            self.setPath(path)
        else:
            self.refresh()

    @studioqt.showArrowCursor
    def _showChangePathDialog(self):
        """
        Open the file dialog for setting a new root path.

        :rtype: str
        """
        path = self.path()
        title = "Choose the root location"
        directory = path

        if not directory:
            directory = os.path.expanduser("~")

        dialog = QtWidgets.QFileDialog(None, QtCore.Qt.WindowStaysOnTopHint)

        dialog.setWindowTitle(title)
        dialog.setDirectory(directory)
        dialog.setFileMode(QtWidgets.QFileDialog.DirectoryOnly)

        if dialog.exec_() == QtWidgets.QFileDialog.Accepted:
            selectedFiles = dialog.selectedFiles()
            if selectedFiles:
                path = selectedFiles[0]

        path = studiolibrary.normPath(path)
        return path

    def isRefreshEnabled(self):
        """
        Return True if the LibraryWidget can be refreshed.
        
        :rtype: bool 
        """
        return self._refreshEnabled

    def setRefreshEnabled(self, enable):
        """
        If enable is False, all updates will be ignored.

        :rtype: bool 
        """
        self._refreshEnabled = enable

    @studioqt.showWaitCursor
    def sync(self):
        """
        Sync any data that might be out of date with the model. 
        
        :rtype: None 
        """
        elapsedTime = time.time()
        self.library().sync()
        self.showToastMessage("Synced")
        elapsedTime = time.time() - elapsedTime

        msg = "Synced items in {0:.3f} seconds."
        msg = msg.format(elapsedTime)

        self.statusWidget().showInfoMessage(msg)

    def refresh(self):
        """
        Refresh all sidebar items and library items.
        
        :rtype: None 
        """
        if self.isRefreshEnabled():
            self.update()

    def update(self):
        """Update the library widget and the data. """
        self.refreshSidebar()
        self.updateWindowTitle()

        if self.path():
            self.refreshItems()
            self.showToastMessage("Refreshed")

    # -----------------------------------------------------------------
    # Methods for the sidebar widget
    # -----------------------------------------------------------------

    def sidebarWidget(self):
        """
        Return the sidebar widget.
        
        :rtype: studioqt.SidebarWidget
        """
        return self._sidebarWidget

    def selectedFolderPath(self):
        """
        Return the selected folder items.

        :rtype: str or None
        """
        return self.sidebarWidget().selectedPath()

    def selectedFolderPaths(self):
        """
        Return the selected folder items.

        :rtype: list[str]
        """
        return self.sidebarWidget().selectedPaths()

    def selectFolderPath(self, path):
        """
        Select the given folder paths.

        :type path: str
        :rtype: None
        """
        self.selectFolderPaths([path])

    def selectFolderPaths(self, paths):
        """
        Select the given folder paths.

        :type paths: list[str]
        :rtype: None
        """
        self.sidebarWidget().selectPaths(paths)

    @studioqt.showWaitCursor
    def refreshSidebar(self):
        """
        Refresh the state of the sidebar widget.
        
        :rtype: None 
        """
        path = self.path()

        if not path:
            return self.showWelcomeDialog()
        elif not os.path.exists(path):
            return self.showPathErrorDialog()

        self.updateSidebar()

    def updateSidebar(self):
        """
        Update the folders to be shown in the folders widget.
        
        :rtype: None 
        """
        rootPath = self.path()

        paths = {
            rootPath: {
                "iconPath": "none",
                "bold": True,
                "text": "FOLDERS",
                "expanded": True,
            }
        }

        queries = [{
            'filters': [('type', 'is', 'Folder')]
        }]

        items = self.library().findItems(queries, libraryWidget=self)

        for item in items:
            if item.DisplayInSidebar:
                path = item.path()
                paths[path] = {}

        self.sidebarWidget().setPaths(paths, root=rootPath)
        self.updateTrashFolder()

    def createFolderContextMenu(self):
        """
        Return the folder menu for the selected folders.

        :rtype: QtWidgets.QMenu
        """

        path = self.selectedFolderPath()

        items = []

        if path:
            item = studiolibrary.itemFromPath(path, libraryWidget=self)

            if item:
                items = [item]
                self._item_ = item

        return self.createItemContextMenu(items)

    # -----------------------------------------------------------------
    # Methods for the items widget
    # -----------------------------------------------------------------

    def itemsWidget(self):
        """
        Return the widget the contains all the items.

        :rtype: studioqt.ItemsWidget
        """
        return self._itemsWidget

    def selectPath(self, path):
        """
        Select the item with the given path.

        :type path: str
        :rtype: None
        """
        self.selectPaths([path])

    def selectPaths(self, paths):
        """
        Select items with the given paths.

        :type paths: list[str]
        :rtype: None
        """
        selection = self.selectedItems()

        self.clearPreviewWidget()
        self.itemsWidget().clearSelection()
        self.itemsWidget().selectPaths(paths)

        if self.selectedItems() != selection:
            self._itemSelectionChanged()

    def selectItems(self, items):
        """
        Select the given items.

        :type items: list[studiolibrary.LibraryItem]
        :rtype: None
        """
        paths = [item.path() for item in items]
        self.selectPaths(paths)

    def scrollToSelectedItem(self):
        """
        Scroll the item widget to the selected item.

        :rtype: None
        """
        self.itemsWidget().scrollToSelectedItem()

    def refreshSelection(self):
        """
        Refresh the current item selection.

        :rtype: None
        """
        items = self.selectedItems()
        self.itemsWidget().clearSelection()
        self.selectItems(items)

    def selectedItems(self):
        """
        Return the selected items.

        :rtype: list[studiolibrary.LibraryItem]
        """
        return self._itemsWidget.selectedItems()

    def clearItems(self):
        """
        Remove all the loaded items.

        :rtype: list[studiolibrary.LibraryItem]
        """
        self.itemsWidget().clear()

    def items(self):
        """
        Return all the loaded items.

        :rtype: list[studiolibrary.LibraryItem]
        """
        return self._items

    def addItem(self, item, select=False):
        """
        Add the given item to the itemsWidget.

        :type item: studiolibrary.LibraryItem
        :type select: bool

        :rtype: None
        """
        self.addItems([item], select=select)

    def addItems(self, items, select=False):
        """
        Add the given items to the itemsWidget.

        :type items: list[studiolibrary.LibraryItem]
        :type select: bool
        
        :rtype: None
        """
        self.itemsWidget().addItems(items)
        self._items.extend(items)

        if select:
            self.selectItems(items)
            self.scrollToSelectedItem()

    def setItems(self, items):
        """
        Set the items for the library widget.

        :rtype: list[studiolibrary.LibraryItem]
        """
        self._items = items

        selectedItems = self.selectedItems()

        self.itemsWidget().setItems(items, sort=True)

        if selectedItems:
            self.selectItems(selectedItems)

    @studioqt.showWaitCursor
    def refreshItems(self):
        """
        Refresh the items for the library widget.

        :rtype: list[studiolibrary.LibraryItem]
        """
        if self.isRefreshEnabled():

            elapsedTime = time.time()

            self.updateItems()

            elapsedTime = time.time() - elapsedTime
            self.showRefreshMessage(elapsedTime)

    def updateItems(self):
        """
        Update the items to be shown in the items widget.

        :rtype: list[studiolibrary.LibraryItem]
        """
        # Create a query using the sidebar and search widgets
        queries = self.sidebarQuery(), self.searchQuery()

        items = self.library().findItems(queries, libraryWidget=self)

        self.setItems(items)

    def sidebarQuery(self):
        """
        Get the query for the sidebar widget.
        
        :rtype: dict
        """
        isRecursive = self.isRecursiveSearchEnabled()
        selectedPaths = self.selectedFolderPaths()

        filters = []

        if isRecursive:
            condition = 'startswith'
        else:
            condition = 'is'

        for path in selectedPaths:
            filter_ = ('folder', condition, path)
            filters.append(filter_)

        return {'operator': 'or', 'filters': filters}

    def searchQuery(self):
        """
        Get the query for the search widget.
        
        :rtype: dict 
        """
        filters = []

        for text in self.searchWidget().text().split():
            filters.append(('path', 'contains', text))

        return {'operator': 'and', 'filters': filters}

    def searchWidgetFilter(self, items):
        """
        Filter the given items using the search widget.
        
        :type items: list[studiolibrary.LibraryItem]
        :rtype: list[studiolibrary.LibraryItem] 
        """
        # Filter the items using the search widget
        validItems = []
        searchFilter = self.searchWidget().searchFilter()
        for item in items:
            if searchFilter.match(item.searchText()):
                validItems.append(item)

        return validItems

    def createItemsFromUrls(self, urls):
        """
        Return a new list of items from the given urls.

        :rtype: list[studiolibrary.LibraryItem]
        """
        return studiolibrary.itemsFromUrls(urls, libraryWidget=self)

    # -----------------------------------------------------------------
    # Support for custom context menus
    # -----------------------------------------------------------------

    def addMenuBarAction(self, name, icon, tip, callback=None):
        """
        Add a button/action to menu bar widget.

        :type name: str
        :type icon: QtWidget.QIcon
        :type tip: str
        :type callback: func
        :type: QtWidget.QAction
        """

        # The method below is needed to fix an issue with PySide2.
        def _callback():
            callback()

        action = self.menuBarWidget().addAction(name)

        if icon:
            action.setIcon(icon)

        if tip:
            action.setToolTip(tip)
            action.setStatusTip(tip)

        if callback:
            action.triggered.connect(_callback)

        return action

    def showGroupByMenu(self):
        """
        Show the group by menu at the group button.

        :rtype: None
        """
        menu = self.itemsWidget().createGroupByMenu()
        widget = self.menuBarWidget().findToolButton("Group By")

        point = widget.mapToGlobal(QtCore.QPoint(0, widget.height()))
        menu.exec_(point)

    def showSortByMenu(self):
        """
        Show the sort by menu at the sort button.

        :rtype: None
        """
        menu = self.itemsWidget().createSortByMenu()
        widget = self.menuBarWidget().findToolButton("Sort By")

        point = widget.mapToGlobal(QtCore.QPoint(0, widget.height()))
        menu.exec_(point)

    def showItemViewMenu(self):
        """
        Show the item settings menu.

        :rtype: None
        """
        menu = self.itemsWidget().createItemSettingsMenu()
        widget = self.menuBarWidget().findToolButton("Item View")

        point = widget.mapToGlobal(QtCore.QPoint(0, widget.height()))
        menu.exec_(point)

    def createNewItemMenu(self):
        """
        Return the create new item menu for adding new folders and items.

        :rtype: QtWidgets.QMenu
        """
        color = self.iconColor()

        icon = studiolibrary.resource().icon("add", color=color)
        menu = QtWidgets.QMenu(self)
        menu.setIcon(icon)
        menu.setTitle("New")

        def _key(cls):
            return cls.MenuOrder

        for cls in sorted(studiolibrary.registeredItems(), key=_key):
            action = cls.createAction(menu, self)

            if action:
                icon = studioqt.Icon(action.icon())
                icon.setColor(self.iconColor())

                action.setIcon(icon)
                menu.addAction(action)

        return menu

    def createSettingsMenu(self):
        """
        Return the settings menu for changing the library widget.

        :rtype: studioqt.Menu
        """
        menu = studioqt.Menu("", self)
        menu.setTitle("Settings")

        action = menu.addAction("Sync")
        action.triggered.connect(self.sync)

        menu.addSeparator()

        if self.DPI_ENABLED:
            action = studioqt.SliderAction("Dpi", menu)
            dpi = self.dpi() * 100.0
            action.slider().setRange(self.DPI_MIN_VALUE, self.DPI_MAX_VALUE)
            action.slider().setValue(dpi)
            action.valueChanged.connect(self._dpiSliderChanged)
            menu.addAction(action)

        action = QtWidgets.QAction("Change Root Path", menu)
        action.triggered.connect(self.showChangePathDialog)
        menu.addAction(action)

        menu.addSeparator()
        theme = self.theme()
        themesMenu = studioqt.ThemesMenu(menu, theme)
        themesMenu.triggered.connect(self.reloadStyleSheet)
        menu.addMenu(themesMenu)

        menu.addSeparator()

        action = QtWidgets.QAction("Show Menu", menu)
        action.setCheckable(True)
        action.setChecked(self.isMenuBarWidgetVisible())
        action.triggered[bool].connect(self.setMenuBarWidgetVisible)
        menu.addAction(action)

        action = QtWidgets.QAction("Show Sidebar", menu)
        action.setCheckable(True)
        action.setChecked(self.isFoldersWidgetVisible())
        action.triggered[bool].connect(self.setFoldersWidgetVisible)
        menu.addAction(action)

        action = QtWidgets.QAction("Show Preview", menu)
        action.setCheckable(True)
        action.setChecked(self.isPreviewWidgetVisible())
        action.triggered[bool].connect(self.setPreviewWidgetVisible)
        menu.addAction(action)

        action = QtWidgets.QAction("Show Status", menu)
        action.setCheckable(True)
        action.setChecked(self.isStatusBarWidgetVisible())
        action.triggered[bool].connect(self.setStatusBarWidgetVisible)
        menu.addAction(action)

        menu.addSeparator()

        action = QtWidgets.QAction("Save Settings", menu)
        action.triggered.connect(self.saveSettings)
        menu.addAction(action)

        action = QtWidgets.QAction("Show Settings", menu)
        action.triggered.connect(self.showSettings)
        menu.addAction(action)

        action = QtWidgets.QAction("Reset Settings", menu)
        action.triggered.connect(self.resetSettings)
        menu.addAction(action)

        if self.trashEnabled():
            menu.addSeparator()
            action = QtWidgets.QAction("Show Trash Folder", menu)
            action.setEnabled(self.trashFolderExists())
            action.setCheckable(True)
            action.setChecked(self.isTrashFolderVisible())
            action.triggered[bool].connect(self.setTrashFolderVisible)
            menu.addAction(action)

        menu.addSeparator()

        action = QtWidgets.QAction("Enable Recursive Search", menu)
        action.setCheckable(True)
        action.setChecked(self.isRecursiveSearchEnabled())
        action.triggered[bool].connect(self.setRecursiveSearchEnabled)
        menu.addAction(action)

        menu.addSeparator()

        viewMenu = self.itemsWidget().createSettingsMenu()
        menu.addMenu(viewMenu)

        menu.addSeparator()

        action = QtWidgets.QAction("Debug Mode", menu)
        action.setCheckable(True)
        action.setChecked(self.isDebug())
        action.triggered[bool].connect(self.setDebugMode)
        menu.addAction(action)

        action = QtWidgets.QAction("Help", menu)
        action.triggered.connect(self.help)
        menu.addAction(action)

        return menu

    def showNewMenu(self):
        """
        Creates and shows the new menu at the new action button.

        :rtype: QtWidgets.QAction
        """
        menu = self.createNewItemMenu()

        point = self.menuBarWidget().rect().bottomLeft()
        point = self.menuBarWidget().mapToGlobal(point)

        menu.show()
        return menu.exec_(point)

    def showSettingsMenu(self):
        """
        Show the settings menu at the current cursor position.

        :rtype: QtWidgets.QAction
        """
        menu = self.createSettingsMenu()

        point = self.menuBarWidget().rect().bottomRight()
        point = self.menuBarWidget().mapToGlobal(point)

        # Align menu to the left of the cursor.
        menu.show()
        x = point.x() - menu.width()
        point.setX(x)

        return menu.exec_(point)

    def showFolderMenu(self, pos=None):
        """
        Show the folder context menu at the current cursor position.

        :type pos: None or QtCore.QPoint
        :rtype: QtWidgets.QAction
        """
        menu = self.createFolderContextMenu()

        point = QtGui.QCursor.pos()
        point.setX(point.x() + 3)
        point.setY(point.y() + 3)
        action = menu.exec_(point)
        menu.close()

        return action

    def showItemsContextMenu(self, pos=None):
        """
        Show the item context menu at the current cursor position.

        :type pos: QtGui.QPoint
        :rtype QtWidgets.QAction
        """
        items = self.itemsWidget().selectedItems()

        menu = self.createItemContextMenu(items)

        point = QtGui.QCursor.pos()
        point.setX(point.x() + 3)
        point.setY(point.y() + 3)
        action = menu.exec_(point)
        menu.close()

        return action

    def createItemContextMenu(self, items):
        """
        Return the item context menu for the given items.

        :type items: list[studiolibrary.LibraryItem]
        :rtype: studiolibrary.ContextMenu
        """
        menu = studioqt.Menu(self)

        item = None

        if items:
            item = items[-1]
            item.contextMenu(menu)

        if not self.isLocked():
            menu.addMenu(self.createNewItemMenu())

            if item:
                editMenu = studioqt.Menu(menu)
                editMenu.setTitle("Edit")
                menu.addMenu(editMenu)

                item.contextEditMenu(editMenu)

                if self.trashEnabled():
                    editMenu.addSeparator()

                    callback = partial(self.showMoveItemsToTrashDialog, [item])

                    action = QtWidgets.QAction("Move to Trash", editMenu)
                    action.setEnabled(not self.isTrashSelected())
                    action.triggered.connect(callback)
                    editMenu.addAction(action)

        menu.addSeparator()
        menu.addMenu(self.createSettingsMenu())

        return menu

    def saveCustomOrder(self):
        """
        Convenience method for saving the custom order.

        :rtype:  None
        """
        self.library().saveItemData(self.items())

    # -------------------------------------------------------------------
    # Support for moving items with drag and drop
    # -------------------------------------------------------------------

    def isCustomOrderEnabled(self):
        """
        Return True if sorting by "Custom Order" is enabled.

        :rtype: bool 
        """
        sortColumn = self.itemsWidget().sortColumn()
        customOrderColumn = self.itemsWidget().columnFromLabel("Custom Order")

        return sortColumn == customOrderColumn

    def isMoveItemsEnabled(self):
        """
        Return True if moving items via drag and drop is enabled.

        :rtype: bool 
        """
        paths = self.selectedFolderPaths()

        if len(paths) != 1:
            return False

        if self.selectedItems():
            return False

        return True

    def createMoveItemsDialog(self):
        """
        Create and return a dialog for moving items.
        
        :rtype: studioqt.MessageBox
        """
        text = 'Would you like to copy or move the selected item/s?'

        dialog = studioqt.createMessageBox(self, "Move or Copy items?", text)
        dialog.buttonBox().clear()

        dialog.addButton(u'Copy', QtWidgets.QDialogButtonBox.AcceptRole)
        dialog.addButton(u'Move', QtWidgets.QDialogButtonBox.AcceptRole)
        dialog.addButton(u'Cancel', QtWidgets.QDialogButtonBox.RejectRole)

        return dialog

    def showMoveItemsDialog(self, items, dst):
        """
        Show the move items dialog for the given items.
        
        :type items: list[studiolibrary.LibraryItem]
        :type dst: str
        :rtype: None
        """
        Copy = 0
        Cancel = 2

        # Check if the items are moving to another folder.
        for item in items:
            if item.dirname() == dst:
                return

        dialog = self.createMoveItemsDialog()
        action = dialog.exec_()
        dialog.close()

        if action == Cancel:
            return

        copy = action == Copy

        self.moveItems(items, dst, copy=copy)

    def moveItems(self, items, dst, copy=False, force=False):
        """
        Move the given items to the destination folder path.
        
        :type items: list[studiolibrary.LibraryItem]
        :type dst: str
        :type copy: bool
        :type force: bool
        :rtype: None 
        """
        self.itemsWidget().clearSelection()

        movedItems = []

        try:
            self.library().blockSignals(True)

            for item in items:

                path = dst + "/" + item.name()

                if force:
                    path = studiolibrary.generateUniquePath(path)

                if copy:
                    item.copy(path)
                else:
                    item.rename(path)

                movedItems.append(item)

        except Exception as error:
            self.showExceptionDialog("Move Error", error)
            raise
        finally:
            self.library().blockSignals(False)

            self.refresh()
            self.selectItems(movedItems)

    # -----------------------------------------------------------------------
    # Support for search
    # -----------------------------------------------------------------------

    def isPreviewWidgetVisible(self):
        """
        Return True if the PreviewWidget is visible, otherwise return False.
        
        :rtype: bool
        """
        return self._previewWidgetVisible

    def isFoldersWidgetVisible(self):
        """
        Return True if the FoldersWidget is visible, otherwise return False.
        
        :rtype: bool
        """
        return self._sidebarWidgetVisible

    def isStatusBarWidgetVisible(self):
        """
        Return True if the StatusWidget is visible, otherwise return False.

        :rtype: bool
        """
        return self._statusBarWidgetVisible

    def isMenuBarWidgetVisible(self):
        """
        Return True if the MenuBarWidget is visible, otherwise return False.
        
        :rtype: bool
        """
        return self.menuBarWidget().isExpanded()

    def setPreviewWidgetVisible(self, value):
        """
        If the value is True then show the PreviewWidget, otherwise hide.

        :type value: bool
        """
        value = bool(value)
        self._previewWidgetVisible = value

        if value:
            self._previewFrame.show()
        else:
            self._previewFrame.hide()

        self.updateViewButton()

    def setFoldersWidgetVisible(self, value):
        """
        If the value is True then show the FoldersWidget, otherwise hide.
        
        :type value: bool
        """
        value = bool(value)
        self._sidebarWidgetVisible = value

        if value:
            self._sidebarFrame.show()
        else:
            self._sidebarFrame.hide()

        self.updateViewButton()

    def setMenuBarWidgetVisible(self, value):
        """
        If the value is True then show the tMenuBarWidget, otherwise hide.

        :type value: bool
        """
        value = bool(value)

        if value:
            self.menuBarWidget().expand()
        else:
            self.menuBarWidget().collapse()

    def setStatusBarWidgetVisible(self, value):
        """
        If the value is True then show the StatusBarWidget, otherwise hide.
        
        :type value: bool
        """
        value = bool(value)

        self._statusBarWidgetVisible = value
        if value:
            self.statusWidget().show()
        else:
            self.statusWidget().hide()

    # -----------------------------------------------------------------------
    # Support for search
    # -----------------------------------------------------------------------

    def itemsVisibleCount(self):
        """
        Return the number of items visible.

        :rtype:  int
        """
        return self._itemsVisibleCount

    def itemsHiddenCount(self):
        """
        Return the number of items hidden.

        :rtype:  int
        """
        return self._itemsHiddenCount

    def setSearchText(self, text):
        """
        Set the search widget text..

        :type text: str
        :rtype: None
        """
        self.searchWidget().setText(text)

    # -----------------------------------------------------------------------
    # Support for custom preview widgets
    # -----------------------------------------------------------------------

    def setCreateWidget(self, widget):
        """
        :type widget: QtWidgets.QWidget
        :rtype: None
        """
        self.setPreviewWidgetVisible(True)
        self.itemsWidget().clearSelection()
        self.setPreviewWidget(widget)

    def clearPreviewWidget(self):
        """
        Set the default preview widget.
        """
        widget = QtWidgets.QWidget(None)
        self.setPreviewWidget(widget)

    def setPreviewWidgetFromItem(self, item):
        """
        :type item: studiolibrary.LibraryItem
        :rtype: None
        """
        if self._currentItem == item:
            logger.debug("The current item preview widget is already set.")
            return

        self._currentItem = item

        if item:
            try:
                item.showPreviewWidget(self)
            except Exception as error:
                self.showErrorMessage(error)
                self.clearPreviewWidget()
                raise
        else:
            self.clearPreviewWidget()

    def previewWidget(self):
        """
        Return the current preview widget.

        :rtype: QtWidgets.QWidget
        """
        return self._previewWidget

    def setPreviewWidget(self, widget):
        """
        Set the preview widget.

        :type widget: QtWidgets.QWidget
        :rtype: None
        """
        if self._previewWidget == widget:
            msg = 'Preview widget already contains widget "{0}"'
            msg.format(widget)
            logger.debug(msg)
        else:
            self.closePreviewWidget()
            self._previewWidget = widget
            if self._previewWidget:
                self._previewFrame.layout().addWidget(self._previewWidget)
                self._previewWidget.show()

    def closePreviewWidget(self):
        """
        Close and delete the preview widget.

        :rtype: None
        """
        if self._previewWidget:
            self._previewWidget.close()

        layout = self._previewFrame.layout()

        while layout.count():
            item = layout.takeAt(0)
            item.widget().hide()
            item.widget().close()
            item.widget().deleteLater()

        self._previewWidget = None

    # -----------------------------------------------------------------------
    # Support for saving and loading the widget state
    # -----------------------------------------------------------------------

    def resetSettings(self):
        """
        Reset the settings to the default settings.

        :rtype: str
        """
        self.setSettings(self.DEFAULT_SETTINGS)

    def settingsPath(self):
        """
        Return the settings path for the LibraryWidget.

        :rtype: str
        """
        return studiolibrary.formatPath(self.SETTINGS_PATH)

    def geometrySettings(self):
        """
        Return the geometry values as a list.

        :rtype: list[int]
        """
        settings = (
            self.window().geometry().x(),
            self.window().geometry().y(),
            self.window().geometry().width(),
            self.window().geometry().height()
        )
        return settings

    def setGeometrySettings(self, settings):
        """
        Set the geometry of the widget with the given values.

        :type settings: list[int]
        :rtype: None
        """
        x, y, width, height = settings

        screenGeometry = QtWidgets.QApplication.desktop().screenGeometry()
        screenWidth = screenGeometry.width()
        screenHeight = screenGeometry.height()

        if x <= 0 or y <= 0 or x >= screenWidth or y >= screenHeight:
            self.centerWindow(width, height)
        else:
            self.window().setGeometry(x, y, width, height)

    def settings(self):
        """
        Return a dictionary with the widget settings.

        :rtype: dict
        """
        settings = {}

        settings['dpi'] = self.dpi()
        settings['geometry'] = self.geometrySettings()
        settings['paneSizes'] = self._splitter.sizes()

        if self.theme():
            settings['theme'] = self.theme().settings()

        settings["trashFolderVisible"] = self.isTrashFolderVisible()
        settings["sidebarWidgetVisible"] = self.isFoldersWidgetVisible()
        settings["previewWidgetVisible"] = self.isPreviewWidgetVisible()
        settings["menuBarWidgetVisible"] = self.isMenuBarWidgetVisible()
        settings["statusBarWidgetVisible"] = self.isStatusBarWidgetVisible()

        settings["recursiveSearchEnabled"] = self.isRecursiveSearchEnabled()

        settings['itemsWidget'] = self.itemsWidget().settings()
        settings['searchWidget'] = self.searchWidget().settings()
        settings['sidebarWidget'] = self.sidebarWidget().settings()

        settings["path"] = self.path()

        return settings

    def setSettings(self, settings):
        """
        Set the widget settings from the given dictionary.

        :type settings: dict
        """
        defaults = copy.deepcopy(self.DEFAULT_SETTINGS)
        settings = studiolibrary.update(defaults, settings)

        isRefreshEnabled = self.isRefreshEnabled()

        try:
            self.setRefreshEnabled(False)
            self.itemsWidget().setToastEnabled(False)

            geometry = settings.get("geometry")
            if geometry:
                self.setGeometrySettings(geometry)

            themeSettings = settings.get("theme")
            if themeSettings:
                self.setThemeSettings(themeSettings)

            if not self.path():
                path = settings.get("path")
                if path and os.path.exists(path):
                    self.setPath(path)

            dpi = settings.get("dpi", 1.0)
            self.setDpi(dpi)

            sizes = settings.get('paneSizes')
            if sizes and len(sizes) == 3:
                self.setSizes(sizes)

            value = settings.get("sidebarWidgetVisible")
            if value is not None:
                self.setFoldersWidgetVisible(value)

            value = settings.get("menuBarWidgetVisible")
            if value is not None:
                self.setMenuBarWidgetVisible(value)

            value = settings.get("previewWidgetVisible")
            if value is not None:
                self.setPreviewWidgetVisible(value)

            value = settings.get("statusBarWidgetVisible")
            if value is not None:
                self.setStatusBarWidgetVisible(value)

            value = settings.get('searchWidget')
            if value is not None:
                self.searchWidget().setSettings(value)

            value = settings.get("recursiveSearchEnabled")
            if value is not None:
                self.setRecursiveSearchEnabled(value)

        finally:
            self.reloadStyleSheet()
            self.setRefreshEnabled(isRefreshEnabled)
            self.refresh()

        value = settings.get('trashFolderVisible')
        if value is not None:
            self.setTrashFolderVisible(value)

        value = settings.get('sidebarWidget', {})
        self.sidebarWidget().setSettings(value)

        value = settings.get('itemsWidget', {})
        self.itemsWidget().setSettings(value)

        self.itemsWidget().setToastEnabled(True)

    def updateSettings(self, settings):
        """
        Save the given path to the settings on disc.

        :type settings: dict
        :rtype: None 
        """
        data = self.readSettings()
        data.update(settings)
        self.saveSettings(data)

    def showSettings(self):
        """Show the settings file."""
        path = self.settingsPath()
        studiolibrary.showInFolder(path)

    def saveSettings(self, settings=None):
        """
        Save the settings to the self.settingsPath() as a json format.

        :type settings: dict or None
        :rtype: None
        """
        settings = settings or self.settings()

        key = self.name()
        path = self.settingsPath()

        data = studiolibrary.readJson(path)
        data[key] = settings

        logger.debug("Saving settings {path}".format(path=path))
        studiolibrary.saveJson(path, data)

    @studioqt.showWaitCursor
    def loadSettings(self):
        """
        Load the settings

        :rtype: None
        """
        self.reloadStyleSheet()
        settings = self.readSettings()
        self.setSettings(settings)

    def readSettings(self):
        """
        Read the settings from the self.settingsPath().

        :rtype: dict
        """
        key = self.name()
        path = self.settingsPath()
        data = {}

        logger.debug(u"Reading settings {path}".format(path=path))

        try:
            data = studiolibrary.readJson(path)
        except Exception as error:
            logging.exception(error)

        return data.get(key, {})

    def isLoaded(self):
        """
        Return True if the Studio Library has been shown

        :rtype: bool
        """
        return self._isLoaded

    def setLoaded(self, loaded):
        """
        Set if the widget has been shown.

        :type loaded: bool
        :rtype: None
        """
        self._isLoaded = loaded

    def setSizes(self, sizes):
        """
        :type sizes: (int, int, int)
        :rtype: None
        """
        fSize, cSize, pSize = sizes

        if pSize == 0:
            pSize = 200

        if fSize == 0:
            fSize = 120

        self._splitter.setSizes([fSize, cSize, pSize])
        self._splitter.setStretchFactor(1, 1)

    def centerWindow(self, width=None, height=None):
        """
        Center the widget to the center of the desktop.

        :rtype: None
        """
        geometry = self.frameGeometry()

        if width:
            geometry.setWidth(width)

        if height:
            geometry.setHeight(height)

        desktop = QtWidgets.QApplication.desktop()

        pos = desktop.cursor().pos()
        screen = desktop.screenNumber(pos)
        centerPoint = desktop.screenGeometry(screen).center()

        geometry.moveCenter(centerPoint)
        self.window().setGeometry(geometry)

    # -----------------------------------------------------------------------
    # Overloading events
    # -----------------------------------------------------------------------

    def event(self, event):
        """
        :type event: QtWidgets.QEvent
        :rtype: QtWidgets.QEvent
        """
        if isinstance(event, QtGui.QKeyEvent):
            if studioqt.isControlModifier() and event.key() == QtCore.Qt.Key_F:
                self.searchWidget().setFocus()

        if isinstance(event, QtGui.QStatusTipEvent):
            self.statusWidget().showInfoMessage(event.tip())

        return QtWidgets.QWidget.event(self, event)

    def keyReleaseEvent(self, event):
        """
        :type event: QtGui.QKeyEvent
        :rtype: None
        """
        for item in self.selectedItems():
            item.keyReleaseEvent(event)
        QtWidgets.QWidget.keyReleaseEvent(self, event)

    def closeEvent(self, event):
        """
        :type event: QtWidgets.QEvent
        :rtype: None
        """
        self.saveSettings()
        QtWidgets.QWidget.closeEvent(self, event)

    def show(self, **kwargs):
        """
        Overriding this method to always raise_ the widget on show.

        Developers can use the kwargs to set platform dependent show options used in subclasses.

        :rtype: None
        """
        QtWidgets.QWidget.show(self)
        self.setWindowState(QtCore.Qt.WindowNoState)
        self.raise_()

    def showEvent(self, event):
        """
        :type event: QtWidgets.QEvent
        :rtype: None
        """
        QtWidgets.QWidget.showEvent(self, event)

        if not self.isLoaded():
            self.setLoaded(True)
            self.setRefreshEnabled(True)
            self.loadSettings()

    # -----------------------------------------------------------------------
    # Support for themes and custom style sheets
    # -----------------------------------------------------------------------

    def dpi(self):
        """
        Return the current dpi for the library widget.

        :rtype: float
        """
        return float(self._dpi)

    def setDpi(self, dpi):
        """
        Set the current dpi for the library widget.

        :rtype: float
        """
        if not self.DPI_ENABLED:
            dpi = 1.0

        self._dpi = dpi

        self.itemsWidget().setDpi(dpi)
        self.menuBarWidget().setDpi(dpi)
        self.sidebarWidget().setDpi(dpi)
        self.statusWidget().setFixedHeight(20 * dpi)

        self._splitter.setHandleWidth(2 * dpi)

        self.showToastMessage("DPI: {0}".format(int(dpi * 100)))

        self.reloadStyleSheet()

    def _dpiSliderChanged(self, value):
        """
        Triggered the dpi action changes value.

        :rtype: float
        """
        dpi = value / 100.0
        self.setDpi(dpi)

    def iconColor(self):
        """
        Return the icon color.

        :rtype: studioqt.Color
        """
        return self.theme().iconColor()

    def setThemeSettings(self, settings):
        """
        Set the theme from the given settings.

        :type settings: dict
        :rtype: None
        """
        theme = studioqt.Theme()
        theme.setSettings(settings)
        self.setTheme(theme)

    def setTheme(self, theme):
        """
        Set the theme.

        :type theme: studioqt.Theme
        :rtype: None
        """
        self._theme = theme
        self._theme.updated.connect(self.reloadStyleSheet)
        self.reloadStyleSheet()

    def theme(self):
        """
        Return the current theme.

        :rtype: studioqt.Theme
        """
        if not self._theme:
            self._theme = studioqt.Theme()

        return self._theme

    def reloadStyleSheet(self):
        """
        Reload the style sheet to the current theme.

        :rtype: None
        """
        theme = self.theme()
        theme.setDpi(self.dpi())

        options = theme.options()
        styleSheet = theme.styleSheet()

        color = studioqt.Color.fromString(options["ITEM_TEXT_COLOR"])
        self.itemsWidget().setTextColor(color)

        color = studioqt.Color.fromString(options["ITEM_TEXT_SELECTED_COLOR"])
        self.itemsWidget().setTextSelectedColor(color)

        color = studioqt.Color.fromString(options["ITEM_BACKGROUND_COLOR"])
        self.itemsWidget().setBackgroundColor(color)

        color = studioqt.Color.fromString(
            options["ITEM_BACKGROUND_HOVER_COLOR"])
        self.itemsWidget().setBackgroundHoverColor(color)

        color = studioqt.Color.fromString(
            options["ITEM_BACKGROUND_SELECTED_COLOR"])
        self.itemsWidget().setBackgroundSelectedColor(color)

        self.setStyleSheet(styleSheet)

        self.searchWidget().update()
        self.menuBarWidget().update()
        self.sidebarWidget().update()

    # -----------------------------------------------------------------------
    # Support for the Trash folder.
    # -----------------------------------------------------------------------

    def trashEnabled(self):
        """
        Return True if moving items to trash.
        
        :rtype: bool 
        """
        return self._trashEnabled

    def setTrashEnabled(self, enable):
        """
        Enable items to be trashed.

        :type enable: bool
        :rtype: None 
        """
        self._trashEnabled = enable

    def isPathInTrash(self, path):
        """
        Return True if the given path is in the Trash path.

        :rtype: bool
        """
        return "trash" in path.lower()

    def trashPath(self):
        """
        Return the trash path for the library.
        
        :rtype: str
        """
        path = self.path()
        return u'{0}/{1}'.format(path, "Trash")

    def trashFolderExists(self):
        """
        Return True if the trash folder exists.
        
        :rtype: bool
        """
        return os.path.exists(self.trashPath())

    def createTrashFolder(self):
        """
        Create the trash folder if it does not exist.
        
        :rtype: None
        """
        path = self.trashPath()
        if not os.path.exists(path):
            os.makedirs(path)

    def isTrashFolderVisible(self):
        """
        Return True if the trash folder is visible to the user.
        
        :rtype: bool
        """
        return self._isTrashFolderVisible

    def setTrashFolderVisible(self, visible):
        """
        Enable the trash folder to be visible to the user.
        
        :type visible: str
        :rtype: None
        """
        self._isTrashFolderVisible = visible
        self.updateTrashFolder()

    def updateTrashFolder(self):
        """
        Update the state of the trash folder.
        
        :rtype: None 
        """
        iconPath = studioqt.resource.get("icons", "delete.png")

        for item in self.sidebarWidget().items():
            if self.trashPath() == item.path():
                item.setIconPath(iconPath)
                item.setHidden(not self.isTrashFolderVisible())

    def isTrashSelected(self):
        """
        Return True if the selected folders is in the trash.
        
        :rtype: bool
        """
        folders = self.selectedFolderPaths()
        for folder in folders:
            if self.isPathInTrash(folder):
                return True

        items = self.selectedItems()
        for item in items:
            if self.isPathInTrash(item.path()):
                return True

        return False

    def moveItemsToTrash(self, items):
        """
        Move the given items to trash path.

        :items items: list[studiolibrary.LibraryItem]
        :rtype: None
        """
        self.createTrashFolder()
        self.moveItems(items, dst=self.trashPath(), force=True)

    def showMoveItemsToTrashDialog(self, items=None):
        """
        Show the "Move to trash" dialog for the selected items.

        :type items: list[studiolibrary.LibraryItem] or None
        :rtype: None
        """
        items = items or self.selectedItems()

        if items:
            title = "Move to trash?"
            text = "Are you sure you want to move the selected" \
                   "item/s to the trash?"

            result = self.showQuestionDialog(title, text)

            if result == QtWidgets.QMessageBox.Yes:
                self.moveItemsToTrash(items)

    # -----------------------------------------------------------------------
    # Support for message boxes
    # -----------------------------------------------------------------------

    def showToastMessage(self, text, duration=1000):
        """
        A convenience method for showing the toast widget with the given text.

        :type text: str
        :type duration: int
        :rtype: None
        """
        self.itemsWidget().showToastMessage(text, duration)

    def showInfoMessage(self, text):
        """
        A convenience method for showing an info message to the user.

        :type text: str
        :rtype: None
        """
        self.statusWidget().showInfoMessage(text)

    def showErrorMessage(self, text):
        """
        A convenience method for showing an error message to the user.

        :type text: str
        :rtype: None
        """
        self.statusWidget().showErrorMessage(text)
        self.setStatusBarWidgetVisible(True)

    def showWarningMessage(self, text):
        """
        A convenience method for showing a warning message to the user.

        :type text: str
        :rtype: None
        """
        self.statusWidget().showWarningMessage(text)
        self.setStatusBarWidgetVisible(True)

    def showRefreshMessage(self, elapsedTime):
        """
        Show how long the current refresh took with the given elapsedTime.

        :type elapsedTime: time.time
        :rtype None
        """
        itemCount = len(self.items())

        plural = ""
        if itemCount > 1:
            plural = "s"

        msg = "Displayed {0} item{1} in {2:.3f} seconds."
        msg = msg.format(itemCount, plural, elapsedTime)
        self.statusWidget().showInfoMessage(msg)

        logger.debug(msg)

    def showInfoDialog(self, title, text):
        """
        A convenience method for showing an information dialog to the user.

        :type title: str
        :type text: str
        :rtype: QMessageBox.StandardButton
        """
        buttons = QtWidgets.QMessageBox.Ok

        return studioqt.MessageBox.question(self, title, text, buttons=buttons)

    def showErrorDialog(self, title, text):
        """
        A convenience method for showing an error dialog to the user.

        :type title: str
        :type text: str
        :rtype: QMessageBox.StandardButton
        """
        self.showErrorMessage(text)
        return studioqt.MessageBox.critical(self, title, text)

    def showExceptionDialog(self, title, error):
        """
        A convenience method for showing an error dialog to the user.

        :type title: str
        :type error: Exception
        :rtype: QMessageBox.StandardButton
        """
        logger.exception(error)
        self.showErrorDialog(title, error)

    def showQuestionDialog(self, title, text, buttons=None):
        """
        A convenience method for showing a question dialog to the user.

        :type title: str
        :type text: str
        :type buttons: list[QMessageBox.StandardButton] 
        :rtype: QMessageBox.StandardButton
        """
        buttons = buttons or \
                  QtWidgets.QMessageBox.Yes | \
                  QtWidgets.QMessageBox.No | \
                  QtWidgets.QMessageBox.Cancel

        return studioqt.MessageBox.question(self, title, text, buttons=buttons)

    def updateWindowTitle(self):
        """
        Update the window title with the version and lock status.

        :rtype: None
        """
        title = "Studio Library - "
        title += studiolibrary.version() + " - " + self.name()

        if self.isLocked():
            title += " (Locked)"

        self.setWindowTitle(title)

    # -----------------------------------------------------------------------
    # Support for locking via regex
    # -----------------------------------------------------------------------

    def updateCreateItemButton(self):
        """
        Update the plus icon depending on if the library widget is locked.

        :rtype: None
        """
        action = self.menuBarWidget().findAction("New Item")

        if self.isLocked():
            pixmap = studioqt.resource.pixmap("lock")
            action.setEnabled(False)
            action.setIcon(pixmap)
        else:
            pixmap = studioqt.resource.pixmap("add")
            action.setEnabled(True)
            action.setIcon(pixmap)

        self.menuBarWidget().refresh()

    def isLocked(self):
        """
        Return lock state of the library.

        :rtype: bool
        """
        return self._isLocked

    def setLocked(self, value):
        """
        Set the state of the widget to not editable.

        :type value: bool
        :rtype: None
        """
        self._isLocked = value

        self.sidebarWidget().setLocked(value)
        self.itemsWidget().setLocked(value)

        self.updateCreateItemButton()
        self.updateWindowTitle()

        self.lockChanged.emit(value)

    def superusers(self):
        """
        Return the superusers for the widget.

        :rtype: list[str]
        """
        return self._superusers

    def setSuperusers(self, superusers):
        """
        Set the valid superusers for the library widget.

        This will lock all folders unless the current user is a superuser.

        :type superusers: list[str]
        :rtype: None
        """
        self._superusers = superusers
        self.updateLock()

    def lockRegExp(self):
        """
        Return the lock regexp used for locking the widget.

        :rtype: str
        """
        return self._lockRegExp

    def setLockRegExp(self, regExp):
        """
        Set the lock regexp used for locking the widget.

        Lock only folders that contain the given regExp in their path.

        :type regExp: str
        :rtype: None
        """
        self._lockRegExp = regExp
        self.updateLock()

    def unlockRegExp(self):
        """
        Return the unlock regexp used for unlocking the widget.

        :rtype: str
        """
        return self._unlockRegExp

    def setUnlockRegExp(self, regExp):
        """
        Return the unlock regexp used for locking the widget.

        Unlock only folders that contain the given regExp in their path.

        :type regExp: str
        :rtype: None
        """
        self._unlockRegExp = regExp
        self.updateLock()

    def isLockRegExpEnabled(self):
        """
        Return True if either the lockRegExp or unlockRegExp has been set.

        :rtype: bool
        """
        return not (
            self.superusers() is None
            and self.lockRegExp() is None
            and self.unlockRegExp() is None
        )

    def updateLock(self):
        """
        Update the lock state for the library.

        This is triggered when the user clicks on a folder.

        :rtype: None
        """
        if not self.isLockRegExpEnabled():
            return

        superusers = self.superusers() or []
        reLocked = re.compile(self.lockRegExp() or "")
        reUnlocked = re.compile(self.unlockRegExp() or "")

        if studiolibrary.user() in superusers:
            self.setLocked(False)

        elif reLocked.match("") and reUnlocked.match(""):

            if superusers:
                # Lock if only the superusers arg is used
                self.setLocked(True)
            else:
                # Unlock if no keyword arguments are used
                self.setLocked(False)

        else:
            folders = self.selectedFolderPaths()

            # Lock the selected folders that match the reLocked regx
            if not reLocked.match(""):
                for folder in folders:
                    if reLocked.search(folder):
                        self.setLocked(True)
                        return

                self.setLocked(False)

            # Unlock the selected folders that match the reUnlocked regx
            if not reUnlocked.match(""):
                for folder in folders:
                    if reUnlocked.search(folder):
                        self.setLocked(False)
                        return

                self.setLocked(True)

    # -----------------------------------------------------------------------
    # Misc
    # -----------------------------------------------------------------------

    def isCompactView(self):
        """
        Return True if both the folder and preview widget are hidden

        :rtype: bool
        """
        return not self.isFoldersWidgetVisible() and not self.isPreviewWidgetVisible()

    def toggleView(self):
        """
        Toggle the preview widget and folder widget visible.

        :rtype: None
        """
        compact = self.isCompactView()

        if studioqt.isControlModifier():
            compact = False
            self.setMenuBarWidgetVisible(compact)

        self.setPreviewWidgetVisible(compact)
        self.setFoldersWidgetVisible(compact)

    def updateViewButton(self):
        """
        Update/referesh the icon on the view button.

        :rtype: None
        """
        compact = self.isCompactView()
        action = self.menuBarWidget().findAction("View")

        if not compact:
            icon = studioqt.resource.icon("view_all")
        else:
            icon = studioqt.resource.icon("view_compact")

        action.setIcon(icon)

        self.menuBarWidget().refresh()

    def isRecursiveSearchEnabled(self):
        """
        Return True if recursive search is enabled.

        :rtype: bool
        """
        return self._recursiveSearchEnabled

    def setRecursiveSearchEnabled(self, value):
        """
        Enable recursive search for searching sub folders.

        :type value: int

        :rtype: None
        """
        self._recursiveSearchEnabled = value
        self.refresh()

    @staticmethod
    def help():
        """
        :rtype: None
        """
        import webbrowser
        webbrowser.open(studiolibrary.HELP_URL)

    def setDebugMode(self, value):
        """
        :type value: bool
        """
        self._isDebug = value

        logger_ = logging.getLogger("studiolibrary")

        if value:
            logger_.setLevel(logging.DEBUG)
        else:
            logger_.setLevel(logging.INFO)

        self.debugModeChanged.emit(value)
        self.globalSignal.debugModeChanged.emit(self, value)

    def isDebug(self):
        """
        :rtype: bool
        """
        return self._isDebug