"""
TP_pipe Pipeline Menu for Maya
--------------------------------
How to run:
  1. Drag-and-drop this .py file directly into the Maya viewport
     (required so "Install Setup Files" can find its own folder on disk —
     pasting into the Script Editor won't work for that feature).
  2. A "TP_pipe" menu will appear in Maya's main menu bar. The first
     entry shows the version number, so you can confirm which build is
     currently running.
  3. Re-running the script is safe — it removes the old menu first so it won't duplicate.

This menu is built one section at a time. Currently included:
  - SETUP: installs BIAS.py (plug-ins folder), userSetup.py (scripts
    folder), and this script itself (scripts folder) into their locations
    in the user's Maya prefs. All three files must sit next to this script
    on disk. Once installed, userSetup.py auto-loads this menu every time
    Maya starts, so students don't need to drag this file in each session.
"""

import datetime
import getpass
import json
import os
import re
import shutil
import sys
import uuid

import maya.cmds as cmds
import maya.mel as mel


MENU_NAME = "pipelineMenu"
PROJECT_MENU_NAME = "projectContextMenu"

# Bump this with every update so it's easy to confirm (right in the menu
# itself) which version of the script is actually running.
TP_PIPE_VERSION = "v2.32.0"

# Files this menu installs, and which Maya folder each one goes in.
# "plugins" -> user prefs plug-ins directory
# "scripts" -> user prefs scripts directory
FILES_TO_INSTALL = {
    "BIAS.py": "plugins",
    "userSetup.py": "scripts",
    "pipeline_menu.py": "scripts",
}

# optionVar key used to remember the current project folder between clicks
# (and across Maya sessions, since optionVars persist).
CURRENT_PROJECT_OPTVAR = "currentProjectPath"

# optionVar key for the parent folder where all projects live — powers
# the "Switch Project" submenu by scanning this folder's subdirectories.
PROJECTS_ROOT_OPTVAR = "projectsRootPath"


# optionVar key used to remember the shot prefix (e.g. "SH") between clicks.
SHOT_PREFIX_OPTVAR = "shotPrefix"

# Shot numbering convention: 4-digit, step of 10 (0010, 0020, 0030...).
SHOT_NUMBER_PADDING = 4
SHOT_NUMBER_STEP = 10

# optionVar keys for saved project settings (output size / start frame).
OUTPUT_WIDTH_OPTVAR = "outputWidth"
OUTPUT_HEIGHT_OPTVAR = "outputHeight"
START_FRAME_OPTVAR = "startFrame"
END_FRAME_OPTVAR = "endFrame"  # scene timeline end, paired with START_FRAME_OPTVAR (2.32.0)

# optionVar keys for a render-specific frame range override (Render Settings
# > Customize > Frame Range). If not set, Apply Settings matches the time
# slider instead.
RENDER_FRAME_START_OPTVAR = "renderFrameStart"
RENDER_FRAME_END_OPTVAR = "renderFrameEnd"

# ------------------------------------------------------------------
# Studio folder template (from the reference project structure).
# ------------------------------------------------------------------

# Named asset types get the full task/software breakdown below.
STANDARD_ASSET_TYPES = ("char", "environ", "prop")

# Standalone asset folders: flat, no per-asset-name/task subfolders.
ASSET_STANDALONE_TYPES = ("camera", "shader", "texture")

# Tasks created inside each named asset folder: assets/<type>/<name>/<task>.
# Each (except texture) gets a work/ + output/ split — see
# build_asset_task_structure. texture stays a flat folder since texture
# files aren't Maya scenes.
ASSET_TASKS = ("model", "rig", "lookdev", "fx", "texture")

# Same idea, but for shot folders: shots/<shot>/<task>/work/<software> +
# shots/<shot>/<task>/output/. Every task has "render" under output (renders
# for that task land there); some tasks additionally keep "cache" (anim/fx,
# for alembic/geo caches — not images) alongside it.
SHOT_TASK_STRUCTURE = {
    "anim": {
        "work": {"maya": {}},
        "output": {"render": {}, "cache": {}},
    },
    "comp": {
        "work": {"nuke": {}, "ae": {}},
        "output": {"render": {}},
    },
    "design": {
        "work": {"ae": {}, "photoshop": {}},
        "output": {"render": {}},
    },
    "dmp": {
        "work": {},
        "output": {"render": {}},
    },
    "fx": {
        "work": {"houdini": {}, "maya": {}},
        "output": {"render": {}, "cache": {}},
    },
    "lighting": {
        "work": {"houdini": {}, "blender": {}, "maya": {}},
        "output": {"render": {}},
    },
    "previs": {
        "work": {"maya": {}},
        "output": {"render": {}},
    },
}


# Project-root folders (relative to the project folder) built at project
# creation time. Shot folders are NOT included here — those are created
# later via Scene Name > Create Shots, using SHOT_TASK_STRUCTURE.
PROJECT_SKELETON_DIRS = [
    "common/scripts",
    "edit/audio",
    "edit/edits",
    "edit/edls",
    "edit/exports",
    "edit/footage",
    "edit/stills",
    "edit/storyboards",
    "io/in",
    "io/out",
    "reference/documents",
    "reference/images",
    "reference/videos",
]

# Per-user sandbox folders (relative to sandbox/<username>), built for the
# current OS user at project creation time.
SANDBOX_PUBLISH_DIRS = [
    "publish/anim/alembic_camera",
    "publish/anim/alembic_geometry",
    "publish/comp/composited_image",
    "publish/design/composited_image",
    "publish/fx/alembic_geometry",
    "publish/lighting/composited_image",
    "publish/lighting/rendered_image",
    "reference/documents",
    "reference/images",
    "reference/videos",
]

# Default Maya project rules written into every "maya" folder (both assets
# and shots), so it functions as its own self-contained Maya workspace.
# Every such folder now sits at exactly <task>/work/maya/, so "images"
# always resolves the same two levels up into <task>/output/render/ —
# no per-task branching needed.
DEFAULT_WORKSPACE_MEL = (
    'workspace -fr "scene" "scenes";\n'
    'workspace -fr "mayaAscii" "scenes";\n'
    'workspace -fr "mayaBinary" "scenes";\n'
    'workspace -fr "images" "../../output/render";\n'
    'workspace -fr "sourceImages" "sourceimages";\n'
    'workspace -fr "renderData" "renderData";\n'
    'workspace -fr "shaders" "renderData/shaders";\n'
    'workspace -fr "iprImages" "renderData/iprImages";\n'
    'workspace -fr "depth" "renderData/depth";\n'
    'workspace -fr "particles" "particles";\n'
    'workspace -fr "clips" "clips";\n'
    'workspace -fr "sound" "sound";\n'
    'workspace -fr "scripts" "scripts";\n'
    'workspace -fr "diskCache" "data";\n'
    'workspace -fr "fileCache" "cache/nCache";\n'
    'workspace -fr "fluidCache" "cache/nCache/fluid";\n'
    'workspace -fr "alembicCache" "cache/alembic";\n'
    'workspace -fr "autoSave" "autosave";\n'
    'workspace -fr "offlineEdit" "scenes/edits";\n'
    'workspace -fr "movie" "movies";\n'
    'workspace -fr "translatorData" "data";\n'
    'workspace -fr "templates" "assets";\n'
)


# ============================================================
# MENU CONSTRUCTION
# ============================================================

def get_project_menu_label():
    """Return the current project's name for the project-context menu label, or 'No Project' if none is set."""
    project_path = get_current_project(warn_if_missing=False)
    if project_path:
        return os.path.basename(project_path.rstrip(os.sep))
    return "No Project"


def build_menu():
    if cmds.menu(MENU_NAME, exists=True):
        cmds.deleteUI(MENU_NAME)
    if cmds.menu(PROJECT_MENU_NAME, exists=True):
        cmds.deleteUI(PROJECT_MENU_NAME)

    g_main_window = mel.eval("$temp1=$gMainWindow")

    # ---------------- TP_pipe menu (fixed, always the same) ----------------
    menu = cmds.menu(MENU_NAME, label="TP_pipe", tearOff=True, parent=g_main_window)

    cmds.menuItem(label=f"Version: {TP_PIPE_VERSION}", enable=False, parent=menu)

    cmds.menuItem(divider=True, dividerLabel="Data Xfer", parent=menu)

    # 2.25.0: Save Setup / Load Existing Setup REMOVED — Todd, after
    # reviewing what was actually under Data Xfer: they did the same job
    # as the new Export/Import Pipeline below but with zero granularity
    # (always every asset, every task, all-or-nothing). save_setup/
    # load_setup_full/load_setup_anim_only/load_setup_lighting_only are
    # still defined in this file, just no longer wired to a menu item
    # (same pattern as every other tool retired this way — see
    # [[pipeline_package]] project memory).
    #
    # 2.26.0: the 2.25.0 4-item submenus (Full Project/All Assets/All
    # Shots/Custom, task-level checkbox picker) are GONE — replaced by a
    # single Asset-Manager-style 3-column drill-down window per side,
    # whole-asset/whole-shot granularity only (no task-level picking).
    # Every function backing the old submenu items (export_pipeline_
    # package_full/all_assets/all_shots, show_export_pipeline_package_
    # custom_window, import_pipeline_package_direct, show_import_
    # pipeline_package_custom_window, the old dialog-based _write_
    # pipeline_package/_prepare_pipeline_package_destination) has been
    # removed outright rather than left unwired — the whole feature was
    # rebuilt, not trimmed, so there was nothing worth keeping around.
    # See the "Export / Import Pipeline" module comment below and
    # [[pipeline_package]] project memory for the full design.
    cmds.menuItem(label="Export Pipeline", command=lambda *a: show_export_pipeline_panel(), parent=menu)
    cmds.menuItem(label="Import Pipeline", command=lambda *a: show_import_pipeline_package(), parent=menu)

    # 2.24.21: Todd — "the name is confusing as i didnt even recall what
    # it did.. so lets change it to 'ingest'". Label/window text only —
    # function/window names left as show_import_file_window/
    # IMPORT_FILE_WINDOW internally to minimize the diff.
    cmds.menuItem(label="Ingest", command=lambda *a: show_import_file_window(), parent=menu)

    cmds.menuItem(divider=True, dividerLabel="TP_pipe", parent=menu)
    cmds.menuItem(label="Install", command=lambda *a: install_setup_files(), parent=menu)
    cmds.menuItem(label="Update", command=lambda *a: update_pipeline(), parent=menu)
    cmds.menuItem(label="Uninstall", command=lambda *a: uninstall_pipeline_from_menu(), parent=menu)

    # ---------------- Project-context menu (label = current project name) ----------------
    project_context_menu = cmds.menu(
        PROJECT_MENU_NAME, label=get_project_menu_label(), tearOff=True, parent=g_main_window
    )

    cmds.menuItem(label="", enable=False, parent=project_context_menu)

    projects_root = get_projects_root()
    available_projects = scan_projects_root(projects_root) if projects_root else []

    if available_projects:
        current_project_path = get_current_project(warn_if_missing=False)
        # Renamed from "Switch Project" to just "Project" — same rollout,
        # same radio-button project list (Todd likes both as-is) — but now
        # also carries the rest of the project-level actions that used to
        # live in their own separate "Project" submenu under Data Manager.
        switch_project_menu = cmds.menuItem(label="Project", subMenu=True, parent=project_context_menu)
        radio_collection = cmds.radioMenuItemCollection(parent=switch_project_menu)
        for candidate_path in available_projects:
            candidate_name = os.path.basename(candidate_path.rstrip(os.sep))
            cmds.menuItem(
                label=candidate_name,
                radioButton=(candidate_path == current_project_path),
                command=lambda *a, p=candidate_path: switch_to_project(p),
                parent=switch_project_menu,
            )
        cmds.menuItem(divider=True, parent=switch_project_menu)
        cmds.menuItem(
            label="Create New Project", command=lambda *a: show_create_project_window(), parent=switch_project_menu
        )
        cmds.menuItem(
            label="Rename Project", command=lambda *a: show_rename_project_window(), parent=switch_project_menu
        )
        cmds.menuItem(
            label="Change Projects Location...", command=lambda *a: select_project_root(), parent=switch_project_menu
        )
    else:
        # 2.31.2: Todd noticed that with a projects root configured but zero
        # project folders under it yet (or no root set at all), there was no
        # way to create the first project from this menu -- only re-picking
        # the master location. Added here so Create New Project is always
        # reachable, not gated behind at least one project already existing.
        # 2.31.3: Todd -- put Create New Project first, and renamed the other
        # item from "Set Master Projects Location" to "Set Project Location".
        cmds.menuItem(
            label="Create New Project", command=lambda *a: show_create_project_window(), parent=project_context_menu
        )
        cmds.menuItem(
            label="Set Project Location", command=lambda *a: select_project_root(), parent=project_context_menu
        )

    # ---------------- FILE ----------------
    cmds.menuItem(divider=True, dividerLabel="File", parent=project_context_menu)
    cmds.menuItem(label="Open", command=lambda *a: file_load(), parent=project_context_menu)
    cmds.menuItem(label="Save", command=lambda *a: file_save(), parent=project_context_menu)
    cmds.menuItem(
        label="Increment and Save", command=lambda *a: file_increment_and_save(), parent=project_context_menu
    )

    cmds.menuItem(label="Save As", command=lambda *a: show_save_as_window(), parent=project_context_menu)
    cmds.menuItem(optionBox=True, command=lambda *a: show_save_as_window(), parent=project_context_menu)

    # ---------------- DATA MANAGER ----------------
    # Create New Project / Select Project / Rename Project used to live in
    # their own "Project" submenu here, but Create New Project and Rename
    # Project moved up into the top "Project" (formerly "Switch Project")
    # submenu instead, next to the radio-button project list. "Select
    # Project" was dropped outright — the radio buttons up there already
    # cover switching. show_select_project_window() is still defined below,
    # just no longer wired to a menu item.
    cmds.menuItem(divider=True, dividerLabel="Data Manager", parent=project_context_menu)

    cmds.menuItem(
        label="Create Shot Folders", command=lambda *a: show_create_shot_folders_window(), parent=project_context_menu
    )
    cmds.menuItem(optionBox=True, command=lambda *a: show_create_shot_folders_window(), parent=project_context_menu)
    cmds.menuItem(
        # 2.24.0: Todd's queued ask (from the 2.23.4 "build a list" round) —
        # moved to sit directly under "Create Shot Folders" instead of after
        # "Set Project Start Frame" (its 2.22.7 placement, below).
        label="Create Asset Folders", command=lambda *a: create_asset_folder_structure(), parent=project_context_menu
    )
    cmds.menuItem(
        label="Create Custom Folder", command=lambda *a: show_create_custom_folder_window(), parent=project_context_menu
    )

    cmds.menuItem(
        label="Set Project Resolution", command=lambda *a: output_size_settings(), parent=project_context_menu
    )
    cmds.menuItem(
        label="Set Project Start Frame", command=lambda *a: start_frame_settings(), parent=project_context_menu
    )

    # ---------------- ASSET MANAGER ----------------
    # Reference Rig Asset / Reference Shade Asset used to live here too,
    # but Asset Manager's "+ Add Asset" (with its Type dropdown) covers
    # the same job for every task type, so those two standalone pickers
    # were removed from the menu as redundant. Their functions
    # (show_reference_rig_asset_window / show_reference_shade_asset_window
    # / show_asset_reference_picker) are still in this file, just no
    # longer wired to a menu item.
    #
    # 2.24.19: same story for "Import Caches" — Todd, after the 2.24.7+
    # cache-attach work: "now it seems we dont need the import caches
    # option in the main pipeline menu since its behavior overlaps with
    # this asset manager" (Asset Manager's own Cache type, via "+ Add
    # Asset," auto-matches/attaches a cache exactly the same way).
    # show_import_caches_panel/show_import_caches_window are both still
    # defined in this file, just no longer wired to a menu item.
    cmds.menuItem(divider=True, dividerLabel="Asset Manager", parent=project_context_menu)
    cmds.menuItem(
        label="Asset Manager", command=lambda *a: show_asset_manager_panel(), parent=project_context_menu
    )
    cmds.menuItem(
        label="Setup Scene", command=lambda *a: setup_scene(), parent=project_context_menu
    )
    cmds.menuItem(
        label="Publish", command=lambda *a: publish_scene(), parent=project_context_menu
    )
    cmds.menuItem(
        label="Export Cache", command=lambda *a: export_selection_to_cache(), parent=project_context_menu
    )
    cmds.menuItem(
        label="Clean Rig Asset", command=lambda *a: clean_rig_asset(), parent=project_context_menu
    )

    # ---------------- RENDER SETTINGS ----------------
    # (2.24.20 briefly had a "Share" section with Export/Import Pipeline
    # Package here — moved into the top-level Data Xfer menu in 2.25.0
    # alongside the rest of the project-transfer tools, then reduced in
    # 2.26.0 to the two single "Export Pipeline"/"Import Pipeline" items.
    # See the "Export / Import Pipeline" module comment near
    # build_asset_task_structure's callers for the full design.)
    cmds.menuItem(divider=True, dividerLabel="Lighting / Rendering", parent=project_context_menu)
    cmds.menuItem(label="Setup Lighting Scene", command=lambda *a: scene_setup(), parent=project_context_menu)
    cmds.menuItem(label="Create Render Layers / AOVs", command=lambda *a: show_create_aovs_window(), parent=project_context_menu)
    cmds.menuItem(label="Apply/Update Light Groups", command=lambda *a: update_light_groups(), parent=project_context_menu)
    cmds.menuItem(label="Apply Render Settings", command=lambda *a: apply_render_settings(), parent=project_context_menu)

    customize_menu = cmds.menuItem(label="Customize", subMenu=True, parent=project_context_menu)
    cmds.menuItem(label="Output Resolution", command=lambda *a: output_size_settings(), parent=customize_menu)
    cmds.menuItem(label="Frame Range", command=lambda *a: customize_render_frame_range(), parent=customize_menu)

    register_scene_opened_job()

    print(
        f'TP_pipe menu built ({TP_PIPE_VERSION}). Look for "TP_pipe" and "{get_project_menu_label()}" '
        "in Maya's main menu bar."
    )


# ============================================================
# SETUP
# ============================================================

def get_source_directory():
    """
    The folder this script lives in on the local drive — plug-in files are
    expected to sit right alongside pipeline_menu.py in that same folder.

    Requires the script to be run as a file (e.g. dragged into the Maya
    viewport, or run via Python > Run Script...), not pasted into the
    Script Editor, since __file__ is only defined in the former case.
    """
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        if os.path.isdir(script_dir):
            return script_dir
    except NameError:
        pass

    cmds.warning(
        "Could not determine the script's folder. Run this script as a file "
        "(drag it into the Maya viewport) rather than pasting it into the "
        "Script Editor."
    )
    return None


def get_plugins_directory():
    """Return the current Maya version's plug-ins folder, creating it if needed."""
    pref_dir = cmds.internalVar(userPrefDir=True)          # e.g. .../maya/2024/prefs/
    version_dir = os.path.abspath(os.path.join(pref_dir, os.pardir))  # .../maya/2024
    plugins_dir = os.path.join(version_dir, "plug-ins")

    if not os.path.isdir(plugins_dir):
        os.makedirs(plugins_dir)

    return plugins_dir


def get_scripts_directory():
    """Return the current Maya version's scripts folder, creating it if needed."""
    scripts_dir = cmds.internalVar(userScriptDir=True)     # e.g. .../maya/2024/scripts/

    if not os.path.isdir(scripts_dir):
        os.makedirs(scripts_dir)

    return scripts_dir


def ensure_bias_plugin_loaded(plugin_path):
    """
    Make sure BIAS.py is loaded right now and set to autoload on future
    Maya startups. Loads via the full path rather than just the filename,
    since Maya's plugin search path is scanned at startup — a file that
    was just copied into the plug-ins folder mid-session may not be found
    by name alone until Maya rescans (or restarts).
    """
    plugin_name = os.path.basename(plugin_path)
    try:
        try:
            is_loaded = cmds.pluginInfo(plugin_name, query=True, loaded=True)
        except Exception:
            is_loaded = False

        if not is_loaded:
            cmds.loadPlugin(plugin_path)

        cmds.pluginInfo(plugin_name, edit=True, autoload=True)
        print(f"{plugin_name}: loaded and set to autoload.")
    except Exception as e:
        cmds.warning(f"Could not load/autoload {plugin_name}: {e}")


def install_setup_files():
    """
    Copy BIAS.py and userSetup.py (expected next to this script) into their
    respective Maya folders:
      BIAS.py       -> user prefs plug-ins directory
      userSetup.py  -> user prefs scripts directory
    """
    source_dir = get_source_directory()
    if not source_dir:
        return

    destinations = {
        "plugins": get_plugins_directory(),
        "scripts": get_scripts_directory(),
    }

    installed = []
    missing = []
    failed = []

    for filename, dest_key in FILES_TO_INSTALL.items():
        src_path = os.path.join(source_dir, filename)
        dest_dir = destinations[dest_key]
        dst_path = os.path.join(dest_dir, filename)

        if not os.path.isfile(src_path):
            missing.append(filename)
            continue

        try:
            shutil.copy2(src_path, dst_path)
            installed.append(f"{filename} -> {dest_dir}")
        except Exception as e:
            failed.append((filename, str(e)))

    if any(name == "BIAS.py" for name in FILES_TO_INSTALL) and os.path.isfile(
        os.path.join(destinations["plugins"], "BIAS.py")
    ):
        ensure_bias_plugin_loaded(os.path.join(destinations["plugins"], "BIAS.py"))

    # Report results.
    print(f"Installed {len(installed)} file(s):")
    for line in installed:
        print(f"  {line}")

    if missing:
        print(f"{len(missing)} file(s) not found in {source_dir}:")
        for f in missing:
            print(f"  {f}")

    if failed:
        print(f"{len(failed)} problem(s):")
        for name, err in failed:
            print(f"  {name}: {err}")

    cmds.confirmDialog(
        title="Install Complete",
        message=(
            f"Installed: {len(installed)}\n"
            f"Missing: {len(missing)}\n"
            f"Problems: {len(failed)}\n\n"
            "See Script Editor output for details."
        ),
        button=["OK"],
    )


def update_pipeline():
    """
    Update the pipeline to a newer version without needing to uninstall
    first: select the updated pipeline_menu.py file directly (BIAS.py and
    userSetup.py are expected to sit right next to it, same as the initial
    install), install all three into their Maya folders (same as Run
    Setup), then immediately reload the freshly-installed pipeline_menu.py
    into THIS session and rebuild the menu — no Maya restart needed.
    """
    file_result = cmds.fileDialog2(
        fileMode=1,
        caption="Select Updated pipeline_menu.py",
        fileFilter="Python Files (*.py)",
    )
    if not file_result:
        return
    source_dir = os.path.dirname(file_result[0])

    destinations = {
        "plugins": get_plugins_directory(),
        "scripts": get_scripts_directory(),
    }

    installed = []
    missing = []
    failed = []

    for filename, dest_key in FILES_TO_INSTALL.items():
        src_path = os.path.join(source_dir, filename)
        dest_dir = destinations[dest_key]
        dst_path = os.path.join(dest_dir, filename)

        if not os.path.isfile(src_path):
            missing.append(filename)
            continue

        try:
            shutil.copy2(src_path, dst_path)
            installed.append(f"{filename} -> {dest_dir}")
        except Exception as e:
            failed.append((filename, str(e)))

    print(f"Updated {len(installed)} file(s):")
    for line in installed:
        print(f"  {line}")
    if missing:
        print(f"{len(missing)} file(s) not found in {source_dir}:")
        for f in missing:
            print(f"  {f}")
    if failed:
        print(f"{len(failed)} problem(s):")
        for name, err in failed:
            print(f"  {name}: {err}")

    if os.path.isfile(os.path.join(destinations["plugins"], "BIAS.py")):
        ensure_bias_plugin_loaded(os.path.join(destinations["plugins"], "BIAS.py"))

    # Reload the just-installed pipeline_menu.py right now, under a module
    # name that won't collide with anything already cached, so the update
    # takes effect immediately instead of waiting for a Maya restart.
    try:
        import importlib.util

        installed_path = os.path.join(get_scripts_directory(), "pipeline_menu.py")
        spec = importlib.util.spec_from_file_location("tp_pipe_updated_menu", installed_path)
        updated_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(updated_module)  # this rebuilds the menu itself
        reload_note = "Menu reloaded in this session — no restart needed."
    except Exception as e:
        reload_note = f"Files updated, but reloading the menu failed ({e}). Restart Maya to pick up the update."

    cmds.confirmDialog(
        title="Pipeline Updated",
        message=(
            f"Installed: {len(installed)}\n"
            f"Missing: {len(missing)}\n"
            f"Problems: {len(failed)}\n\n"
            f"{reload_note}\n\n"
            "See Script Editor output for details."
        ),
        button=["OK"],
    )


def uninstall_pipeline_from_menu():
    """
    Uninstall TP_pipe from within the running menu — no separate script
    needed. Prompts whether to keep saved settings (current project, shot
    prefix, output size, etc.) or clear everything.
    """
    choice = cmds.confirmDialog(
        title="Uninstall TP_pipe",
        message=(
            "Remove TP_pipe from this machine?\n\n"
            "Choose whether to keep your saved settings (current project, "
            "shot prefix, output size, etc.) or clear everything."
        ),
        button=["Keep Settings", "Full Uninstall", "Cancel"],
        defaultButton="Keep Settings",
        cancelButton="Cancel",
        dismissString="Cancel",
    )
    if choice == "Cancel":
        return

    full_uninstall = choice == "Full Uninstall"

    # Remove both menus from this session.
    menus_removed = 0
    for name in (MENU_NAME, PROJECT_MENU_NAME):
        if cmds.menu(name, exists=True):
            cmds.deleteUI(name)
            menus_removed += 1

    # Kill our scriptJobs for this session (any other code the student
    # added to userSetup.py themselves is left untouched).
    killed = 0
    for job_str in cmds.scriptJob(listJobs=True):
        if "SceneOpened" not in job_str:
            continue
        if "apply_saved_settings" in job_str:
            job_id = int(job_str.split(":")[0])
            try:
                cmds.scriptJob(kill=job_id, force=True)
                killed += 1
            except Exception:
                pass

    # Clear any cached copy of the pipeline module from memory.
    for mod_name in ("pipeline_menu", "tp_pipe_installed_menu", "tp_pipe_updated_menu"):
        if mod_name in sys.modules:
            del sys.modules[mod_name]

    plugins_dir = get_plugins_directory()
    scripts_dir = get_scripts_directory()

    removed_files = []
    for path, label in (
        (os.path.join(plugins_dir, "BIAS.py"), "BIAS.py"),
        (os.path.join(scripts_dir, "pipeline_menu.py"), "pipeline_menu.py"),
    ):
        if os.path.isfile(path):
            try:
                os.remove(path)
                removed_files.append(label)
            except Exception as e:
                cmds.warning(f"Could not remove {label}: {e}")

    # Strip only the TP_pipe-added sections out of userSetup.py, leaving
    # any other custom code the student has there untouched.
    user_setup_path = os.path.join(scripts_dir, "userSetup.py")
    marker = "# ------------------------------------------------------------------\n# TP_pipe Pipeline Menu"
    user_setup_cleaned = False
    if os.path.isfile(user_setup_path):
        try:
            with open(user_setup_path, "r") as f:
                content = f.read()
            idx = content.find(marker)
            if idx != -1:
                with open(user_setup_path, "w") as f:
                    f.write(content[:idx].rstrip() + "\n")
                user_setup_cleaned = True
        except Exception as e:
            cmds.warning(f"Could not clean userSetup.py: {e}")

    cleared_settings = []
    if full_uninstall:
        for optvar in (
            CURRENT_PROJECT_OPTVAR,
            SHOT_PREFIX_OPTVAR,
            OUTPUT_WIDTH_OPTVAR,
            OUTPUT_HEIGHT_OPTVAR,
            START_FRAME_OPTVAR,
            RENDER_FRAME_START_OPTVAR,
            RENDER_FRAME_END_OPTVAR,
        ):
            if cmds.optionVar(exists=optvar):
                cmds.optionVar(remove=optvar)
                cleared_settings.append(optvar)

    print(
        f"TP_pipe uninstalled ({'full' if full_uninstall else 'settings kept'}). "
        f"Menus removed: {menus_removed}. scriptJobs killed: {killed}. "
        f"Files removed: {removed_files}. userSetup.py cleaned: {user_setup_cleaned}. "
        f"Settings cleared: {cleared_settings if full_uninstall else 'none (kept)'}"
    )

    message = (
        "TP_pipe has been removed:\n"
        f"- Menus removed from this session ({menus_removed})\n"
        "- Cached module cleared from memory\n"
        f"- Files removed: {', '.join(removed_files) if removed_files else '(none found)'}\n"
        "- userSetup.py cleaned (your other code preserved)\n\n"
    )
    if full_uninstall:
        message += "Saved settings were also cleared."
    else:
        message += "Saved settings were kept — reinstalling will pick up right where you left off."

    cmds.confirmDialog(title="TP_pipe Uninstalled", message=message, button=["OK"])


# ============================================================
# PROJECT SETUP
# ============================================================

def _prompt_for_name(title, message):
    """Show a simple text-entry dialog and return the trimmed string, or None if cancelled/empty."""
    result = cmds.promptDialog(
        title=title,
        message=message,
        button=["Create", "Cancel"],
        defaultButton="Create",
        cancelButton="Cancel",
        dismissString="Cancel",
    )
    if result != "Create":
        return None

    text = cmds.promptDialog(query=True, text=True).strip()
    if not text:
        cmds.warning("Name cannot be empty.")
        return None

    return text


_WORKSPACE_RULE_PATTERN = re.compile(r'workspace -fr "\w+" "([^"]+)";')


def _standard_workspace_subfolders():
    """
    Every physical subfolder DEFAULT_WORKSPACE_MEL's file rules point at,
    inside the maya folder itself. Skips "images" — its rule value starts
    with ".." because it deliberately points *outside* the maya folder at
    the task's own output/render (build_asset_task_structure/
    build_folder_tree already create that one). De-dupes repeated targets
    (diskCache and translatorData both map to "data").
    """
    targets = []
    seen = set()
    for target in _WORKSPACE_RULE_PATTERN.findall(DEFAULT_WORKSPACE_MEL):
        if target.startswith("..") or target in seen:
            continue
        seen.add(target)
        targets.append(target)
    return targets


def write_default_workspace(folder_path):
    """
    Write a default workspace.mel into folder_path if one doesn't already
    exist, and physically create every standard Maya project subfolder
    workspace.mel's file rules point at (scenes, sourceimages,
    renderData/shaders, renderData/iprImages, renderData/depth,
    particles, clips, sound, scripts, data, cache/nCache,
    cache/nCache/fluid, cache/alembic, autosave, scenes/edits, movies,
    assets) — so a freshly-created "maya" folder looks like a real Maya
    project on disk right away, not just via file-rule mappings Maya
    would otherwise create lazily on first use.

    2026-08-27: added after Todd noticed a scene saved via this tool
    (which writes straight into the maya folder itself — see
    asset_task_maya_dir/_save_scene_as, unchanged) never actually
    created a physical "scenes" subfolder underneath it. The folder
    creation runs every call (exist_ok=True, so it's a harmless no-op
    once they exist) rather than only alongside a fresh workspace.mel,
    so calling this again on an already-set-up "maya" folder backfills
    any subfolders it's still missing.

    "images" is deliberately excluded — see _standard_workspace_subfolders.
    """
    workspace_path = os.path.join(folder_path, "workspace.mel")
    if not os.path.isfile(workspace_path):
        with open(workspace_path, "w") as f:
            f.write(DEFAULT_WORKSPACE_MEL)

    for subfolder in _standard_workspace_subfolders():
        os.makedirs(os.path.join(folder_path, subfolder), exist_ok=True)


def build_asset_task_structure(asset_dir, tasks=None):
    """
    Create <asset_dir>/<task>/work/maya and <asset_dir>/<task>/output/render
    for each task (model/rig/lookdev/fx) — the work/maya folder gets its own
    workspace.mel so it functions as a self-contained Maya workspace, with
    "images" pointing at the sibling output/render folder. texture is the
    exception — just a flat folder, no work/output split, since texture
    files aren't Maya scene files.

    2.24.20: tasks (optional) restricts this to a specific subset of
    ASSET_TASKS instead of building all of them — added for Export/Import
    Pipeline Package, where a collaborator may only need e.g. model+lookdev,
    not every task. Every existing caller omits this (defaults to None ->
    all tasks), so behavior is unchanged for them.
    """
    for task in tasks if tasks is not None else ASSET_TASKS:
        task_dir = os.path.join(asset_dir, task)
        if task == "texture":
            os.makedirs(task_dir, exist_ok=True)
        else:
            maya_dir = os.path.join(task_dir, "work", "maya")
            os.makedirs(maya_dir, exist_ok=True)
            write_default_workspace(maya_dir)
            os.makedirs(os.path.join(task_dir, "output", "render"), exist_ok=True)


def build_project_skeleton(project_path):
    """
    Build the standard project skeleton at project_path: assets
    (char/environ/prop as flat type containers, plus camera/shader/texture),
    common, edit, io, reference, and a sandbox folder for the current user.
    Sets project_path as the current project. Safe to call on a folder that
    already exists — everything uses exist_ok / makedirs(exist_ok=True).
    """
    os.makedirs(project_path, exist_ok=True)
    cmds.optionVar(stringValue=(CURRENT_PROJECT_OPTVAR, project_path))
    cmds.savePrefs(general=True)
    build_menu()

    # Default output settings for every shot in a newly-created project
    # (2.32.0): resolution 1920x1080, frame range 1001-1200. These are the
    # same optionVars Output Size / Customize Frame Range / Starting Frame
    # already read and write, so a fresh project starts with sane defaults
    # instead of an empty/unset state -- Setup Scene's render settings and
    # the SceneOpened auto-apply job (apply_saved_settings) both pick these
    # up automatically for every shot scene, timeline included.
    cmds.optionVar(intValue=(OUTPUT_WIDTH_OPTVAR, 1920))
    cmds.optionVar(intValue=(OUTPUT_HEIGHT_OPTVAR, 1080))
    cmds.optionVar(intValue=(RENDER_FRAME_START_OPTVAR, 1001))
    cmds.optionVar(intValue=(RENDER_FRAME_END_OPTVAR, 1200))
    cmds.optionVar(intValue=(START_FRAME_OPTVAR, 1001))
    cmds.optionVar(intValue=(END_FRAME_OPTVAR, 1200))

    # Root-level folders (common, edit, io, reference).
    for rel_path in PROJECT_SKELETON_DIRS:
        os.makedirs(os.path.join(project_path, rel_path), exist_ok=True)

    # Assets: standard + standalone types are just flat containers here.
    # Task subfolders get created per-asset once a named asset exists.
    assets_dir = os.path.join(project_path, "assets")
    os.makedirs(assets_dir, exist_ok=True)
    for type_name in STANDARD_ASSET_TYPES:
        os.makedirs(os.path.join(assets_dir, type_name), exist_ok=True)
    for standalone_type in ASSET_STANDALONE_TYPES:
        os.makedirs(os.path.join(assets_dir, standalone_type), exist_ok=True)

    # Shots: an empty sibling of assets. Individual shot folders get
    # created on demand via Create Shot Folders.
    os.makedirs(os.path.join(project_path, "shots"), exist_ok=True)

    # Sandbox for the current OS user.
    username = getpass.getuser()
    sandbox_dir = os.path.join(project_path, "sandbox", username)
    for rel_path in SANDBOX_PUBLISH_DIRS:
        os.makedirs(os.path.join(sandbox_dir, rel_path), exist_ok=True)


def create_project_folder():
    """
    Ask for the project's location and name in a single native dialog (a
    Save-style file picker lets the student navigate to a destination and
    type a name in that same window), then build the standard project
    skeleton there. Individual named assets (and their task subfolders)
    are created later via File > Save As > Asset. Shot folders are
    created later, via Project Settings > Create Shot Folders.
    """
    result = cmds.fileDialog2(
        fileMode=0,
        caption="Select Location and Enter Project Name",
        okCaption="Create",
    )
    if not result:
        return

    project_path = result[0]
    # Defensive: some Windows Save dialogs append a literal ".*" to the
    # typed name when no explicit extension is given.
    if project_path.endswith(".*"):
        project_path = project_path[:-2]

    if os.path.isdir(project_path):
        cmds.warning(f"Folder already exists: {project_path}")
        return

    build_project_skeleton(project_path)

    print(f"Created project folder: {project_path}")
    cmds.confirmDialog(
        title="Project Created",
        message=f"Project created at:\n{project_path}",
        button=["OK"],
    )


CREATE_PROJECT_WINDOW = "createProjectWindow"


def show_create_project_window():
    """
    Pop-up window (matching Create Shot Folders' style) for creating a new
    project: browse for a location and type a name.
    """
    if cmds.window(CREATE_PROJECT_WINDOW, exists=True):
        cmds.deleteUI(CREATE_PROJECT_WINDOW)

    window = cmds.window(CREATE_PROJECT_WINDOW, title="Create New Project", sizeable=False, width=340)
    cmds.columnLayout(adjustableColumn=True, columnAlign="left", rowSpacing=6, columnOffset=("both", 12))

    cmds.text(label="")  # top spacer
    cmds.text(label="Create New Project", font="boldLabelFont", align="left")
    cmds.separator(height=10, style="in")

    cmds.text(label="Project Location", align="left")

    def on_browse(*_args):
        result = cmds.fileDialog2(fileMode=3, caption="Select Project Location")
        if result:
            cmds.textField(location_field, edit=True, text=result[0])

    cmds.rowLayout(numberOfColumns=2, columnWidth2=(220, 90), adjustableColumn=1)
    # 2.31.2: default to the configured projects root (when one is set) so a
    # project created via the empty-state "Create New Project" item lands
    # somewhere scan_projects_root() will actually find it afterward -- still
    # browsable/overridable via the Browse button either way.
    default_location = get_projects_root() or ""
    location_field = cmds.textField(text=default_location, editable=False)
    cmds.button(label="Browse...", command=on_browse)
    cmds.setParent("..")

    cmds.separator(height=10, style="in")

    cmds.rowLayout(numberOfColumns=2, columnWidth2=(90, 180), adjustableColumn=2)
    cmds.text(label="Project Name")
    name_field = cmds.textField(text="")
    cmds.setParent("..")

    cmds.separator(height=10, style="in")

    def on_create(*_args):
        location = cmds.textField(location_field, query=True, text=True).strip()
        if not location:
            cmds.warning("Select a project location first.")
            return

        name = cmds.textField(name_field, query=True, text=True).strip()
        if not name:
            cmds.warning("Enter a project name.")
            return

        project_path = os.path.join(location, name)
        if os.path.isdir(project_path):
            cmds.warning(f"Folder already exists: {project_path}")
            return

        build_project_skeleton(project_path)
        print(f"Created project folder: {project_path}")

        cmds.deleteUI(window)

        cmds.confirmDialog(
            title="Project Created",
            message=f"Project created at:\n{project_path}",
            button=["OK"],
        )

    cmds.columnLayout(adjustableColumn=True, columnAlign="center")
    cmds.rowLayout(numberOfColumns=2, columnAttach2=("both", "both"), columnOffset2=(0, 8))
    cmds.button(label="Create", width=85, command=on_create)
    cmds.button(label="Cancel", width=85, command=lambda *a: cmds.deleteUI(window))
    cmds.setParent("..")
    cmds.setParent("..")

    cmds.text(label="")  # bottom spacer

    cmds.showWindow(window)


SELECT_PROJECT_WINDOW = "selectProjectWindow"


def show_select_project_window():
    """Pop-up window (matching Create Project's location picker) to browse for an existing project and select it."""
    if cmds.window(SELECT_PROJECT_WINDOW, exists=True):
        cmds.deleteUI(SELECT_PROJECT_WINDOW)

    window = cmds.window(SELECT_PROJECT_WINDOW, title="Select Project", sizeable=False, width=340)
    cmds.columnLayout(adjustableColumn=True, columnAlign="left", rowSpacing=6, columnOffset=("both", 12))

    cmds.text(label="")  # top spacer
    cmds.text(label="Select Project", font="boldLabelFont", align="left")
    cmds.separator(height=10, style="in")

    cmds.text(label="Project Location", align="left")

    def on_browse(*_args):
        result = cmds.fileDialog2(fileMode=3, caption="Select Existing Project Folder")
        if result:
            cmds.textField(location_field, edit=True, text=result[0])

    cmds.rowLayout(numberOfColumns=2, columnWidth2=(220, 90), adjustableColumn=1)
    # 2.31.2: default to the configured projects root (when one is set) so a
    # project created via the empty-state "Create New Project" item lands
    # somewhere scan_projects_root() will actually find it afterward -- still
    # browsable/overridable via the Browse button either way.
    default_location = get_projects_root() or ""
    location_field = cmds.textField(text=default_location, editable=False)
    cmds.button(label="Browse...", command=on_browse)
    cmds.setParent("..")

    cmds.separator(height=10, style="in")

    def on_select(*_args):
        project_path = cmds.textField(location_field, query=True, text=True).strip()
        if not project_path:
            cmds.warning("Select a project folder first.")
            return

        cmds.optionVar(stringValue=(CURRENT_PROJECT_OPTVAR, project_path))
        cmds.savePrefs(general=True)
        build_menu()

        cmds.deleteUI(window)

        print(f"Current project set to: {project_path}")
        cmds.confirmDialog(
            title="Project Selected",
            message=f"Current project set to:\n{project_path}",
            button=["OK"],
        )

    cmds.columnLayout(adjustableColumn=True, columnAlign="center")
    cmds.rowLayout(numberOfColumns=2, columnAttach2=("both", "both"), columnOffset2=(0, 8))
    cmds.button(label="Select", width=85, command=on_select)
    cmds.button(label="Cancel", width=85, command=lambda *a: cmds.deleteUI(window))
    cmds.setParent("..")
    cmds.setParent("..")

    cmds.text(label="")  # bottom spacer

    cmds.showWindow(window)


RENAME_PROJECT_WINDOW = "renameProjectWindow"


def show_rename_project_window():
    """Show the current project name, take a new name, confirm, then rename the folder on disk."""
    project_path = get_current_project()
    if not project_path:
        return

    current_name = os.path.basename(project_path.rstrip(os.sep))

    if cmds.window(RENAME_PROJECT_WINDOW, exists=True):
        cmds.deleteUI(RENAME_PROJECT_WINDOW)

    window = cmds.window(RENAME_PROJECT_WINDOW, title="Rename Project", sizeable=False, width=340)
    cmds.columnLayout(adjustableColumn=True, columnAlign="left", rowSpacing=6, columnOffset=("both", 12))

    cmds.text(label="")  # top spacer
    cmds.text(label="Rename Project", font="boldLabelFont", align="left")
    cmds.separator(height=10, style="in")

    cmds.text(label=f"Current Project: {current_name}", align="left")

    cmds.separator(height=10, style="in")

    cmds.rowLayout(numberOfColumns=2, columnWidth2=(90, 180), adjustableColumn=2)
    cmds.text(label="New Name")
    new_name_field = cmds.textField(text="")
    cmds.setParent("..")

    cmds.separator(height=10, style="in")

    def on_rename(*_args):
        new_name = cmds.textField(new_name_field, query=True, text=True).strip()
        if not new_name:
            cmds.warning("Enter a new project name.")
            return
        if new_name == current_name:
            cmds.warning("New name is the same as the current name.")
            return

        parent_dir = os.path.dirname(project_path.rstrip(os.sep))
        new_path = os.path.join(parent_dir, new_name)

        if os.path.isdir(new_path):
            cmds.warning(f"A folder already exists at: {new_path}")
            return

        confirm = cmds.confirmDialog(
            title="Confirm Rename",
            message=f'Rename project:\n"{current_name}"\nto\n"{new_name}"?',
            button=["Rename", "Cancel"],
            defaultButton="Rename",
            cancelButton="Cancel",
            dismissString="Cancel",
        )
        if confirm != "Rename":
            return

        try:
            os.rename(project_path, new_path)
        except Exception as e:
            cmds.warning(f"Could not rename project folder: {e}")
            return

        cmds.optionVar(stringValue=(CURRENT_PROJECT_OPTVAR, new_path))
        cmds.savePrefs(general=True)
        build_menu()

        # If the currently open scene lived inside the renamed project, the
        # file itself moved along with the folder rename — but Maya's
        # internal tracking of "what scene is open" still points at the
        # old path string. Update that reference to match reality.
        current_scene_path = cmds.file(query=True, sceneName=True)
        if current_scene_path:
            normalized_old = os.path.normpath(project_path)
            normalized_scene = os.path.normpath(current_scene_path)
            if normalized_scene == normalized_old or normalized_scene.startswith(normalized_old + os.sep):
                relative_part = os.path.relpath(normalized_scene, normalized_old)
                new_scene_path = os.path.join(new_path, relative_part)
                cmds.file(rename=new_scene_path)
                align_maya_project()
                print(f"Repathed open scene to: {new_scene_path}")

        cmds.deleteUI(window)

        print(f"Renamed project: {project_path} -> {new_path}")
        cmds.confirmDialog(
            title="Project Renamed",
            message=f"Project renamed to:\n{new_path}",
            button=["OK"],
        )

    cmds.columnLayout(adjustableColumn=True, columnAlign="center")
    cmds.rowLayout(numberOfColumns=2, columnAttach2=("both", "both"), columnOffset2=(0, 8))
    cmds.button(label="Rename", width=85, command=on_rename)
    cmds.button(label="Cancel", width=85, command=lambda *a: cmds.deleteUI(window))
    cmds.setParent("..")
    cmds.setParent("..")

    cmds.text(label="")  # bottom spacer

    cmds.showWindow(window)


def create_asset_type(type_name):
    """Create <current project>/assets/<type_name> as a flat type container."""
    project_path = get_current_project()
    if not project_path:
        return

    assets_dir = os.path.join(project_path, "assets")
    if not os.path.isdir(assets_dir):
        os.makedirs(assets_dir)

    type_path = os.path.join(assets_dir, type_name)
    if os.path.isdir(type_path):
        cmds.warning(f"Asset type folder already exists: {type_path}")
        return

    os.makedirs(type_path)

    print(f"Created asset type folder: {type_path}")
    cmds.confirmDialog(
        title="Asset Type Created",
        message=f"Asset type folder created at:\n{type_path}",
        button=["OK"],
    )


def create_custom_asset_type():
    """Prompt for a custom asset type name, then create it under assets/."""
    type_name = _prompt_for_name("Custom Asset Type", "Asset Type Name:")
    if not type_name:
        return

    create_asset_type(type_name)


def create_all_asset_types():
    """Create all standard asset type folders (char, environ, prop) at once, as flat containers."""
    project_path = get_current_project()
    if not project_path:
        return

    assets_dir = os.path.join(project_path, "assets")
    if not os.path.isdir(assets_dir):
        os.makedirs(assets_dir)

    created = []
    skipped = []

    for type_name in STANDARD_ASSET_TYPES:
        type_path = os.path.join(assets_dir, type_name)
        if os.path.isdir(type_path):
            skipped.append(type_name)
            continue
        os.makedirs(type_path)
        created.append(type_name)

    print(f"Created {len(created)} asset type folder(s) in: {assets_dir}")
    for name in created:
        print(f"  {name}")
    if skipped:
        print(f"Skipped {len(skipped)} already-existing type(s):")
        for name in skipped:
            print(f"  {name}")

    cmds.confirmDialog(
        title="Asset Types Created",
        message=(
            f"Created: {len(created)}\n"
            f"Already existed: {len(skipped)}\n\n"
            "See Script Editor output for details."
        ),
        button=["OK"],
    )



# ============================================================
# SCENE NAME
# ============================================================

def get_shot_prefix(warn_if_missing=True):
    """Return the stored shot prefix, or None if it hasn't been set yet."""
    if cmds.optionVar(exists=SHOT_PREFIX_OPTVAR):
        return cmds.optionVar(query=SHOT_PREFIX_OPTVAR)

    if warn_if_missing:
        cmds.warning('No shot prefix set. Use "Set Shot Prefix" first.')
    return None


def get_current_project(warn_if_missing=True):
    """Return the stored current project path, or None if it hasn't been set yet."""
    if cmds.optionVar(exists=CURRENT_PROJECT_OPTVAR):
        path = cmds.optionVar(query=CURRENT_PROJECT_OPTVAR)
        if os.path.isdir(path):
            return path

    if warn_if_missing:
        cmds.warning('No current project set. Use "Create Project Folder" first.')
    return None


def get_projects_root():
    """Return the configured parent folder where all projects live, or None if not set/invalid."""
    if cmds.optionVar(exists=PROJECTS_ROOT_OPTVAR):
        path = cmds.optionVar(query=PROJECTS_ROOT_OPTVAR)
        if os.path.isdir(path):
            return path
    return None


def select_project_root():
    """Choose the parent folder where all projects live; Switch Project is built from whatever's found there."""
    result = cmds.fileDialog2(fileMode=3, caption="Select Projects Folder", okCaption="Set")
    if not result:
        return

    root_path = result[0]
    cmds.optionVar(stringValue=(PROJECTS_ROOT_OPTVAR, root_path))
    cmds.savePrefs(general=True)

    print(f"Projects folder set to: {root_path}")
    cmds.confirmDialog(
        title="Projects Folder Set",
        message=(
            f"Projects folder set to:\n{root_path}\n\n"
            '"Switch Project" will now list whatever project folders are found there.'
        ),
        button=["OK"],
    )
    cmds.evalDeferred(build_menu)


def scan_projects_root(root_path):
    """
    Return full paths of subfolders under root_path that look like TP_pipe
    projects (contain an assets folder), sorted by name.
    """
    if not os.path.isdir(root_path):
        return []
    candidates = []
    for name in sorted(os.listdir(root_path)):
        candidate_path = os.path.join(root_path, name)
        if os.path.isdir(candidate_path) and os.path.isdir(os.path.join(candidate_path, "assets")):
            candidates.append(candidate_path)
    return candidates


def switch_to_project(project_path):
    """Switch the current project to project_path and rebuild the menu so everything reflects it."""
    if not os.path.isdir(project_path):
        cmds.warning(f"Project folder no longer exists: {project_path}")
        return
    cmds.optionVar(stringValue=(CURRENT_PROJECT_OPTVAR, project_path))
    cmds.savePrefs(general=True)
    # Deferred rather than called directly — this callback is running from
    # inside a menu item's own click handler, and rebuilding (deleting and
    # recreating) that same menu synchronously mid-click is a risky pattern
    # in Maya. Deferring lets Maya finish processing the click first.
    cmds.evalDeferred(build_menu)


def get_scenes_directory(project_path):
    """Return <project>/shots, creating it if needed."""
    shots_dir = os.path.join(project_path, "shots")
    if not os.path.isdir(shots_dir):
        os.makedirs(shots_dir)
    return shots_dir


def format_shot_name(prefix, number):
    return f"{prefix}{str(number).zfill(SHOT_NUMBER_PADDING)}"


def get_existing_shot_numbers(scenes_dir, prefix):
    """Scan the shots folder for existing <prefix><digits> folders and return their numbers, sorted."""
    numbers = []
    if not os.path.isdir(scenes_dir):
        return numbers

    for name in os.listdir(scenes_dir):
        if name.startswith(prefix) and os.path.isdir(os.path.join(scenes_dir, name)):
            suffix = name[len(prefix):]
            if suffix.isdigit():
                numbers.append(int(suffix))

    return sorted(numbers)


def _prompt_for_int(title, message):
    """Show a text-entry dialog and return an int, or None if cancelled/invalid."""
    result = cmds.promptDialog(
        title=title,
        message=message,
        button=["OK", "Cancel"],
        defaultButton="OK",
        cancelButton="Cancel",
        dismissString="Cancel",
    )
    if result != "OK":
        return None

    text = cmds.promptDialog(query=True, text=True).strip()
    try:
        return int(text)
    except ValueError:
        cmds.warning(f'"{text}" is not a valid number.')
        return None


def build_folder_tree(base_path, tree):
    """
    Recursively create folders from a nested dict structure (keys are
    folder names, values are their own nested dicts, {} for a leaf).
    Any folder literally named "maya" also gets a default workspace.mel,
    so it works as a self-contained Maya workspace.
    """
    for name, subtree in tree.items():
        folder_path = os.path.join(base_path, name)
        os.makedirs(folder_path, exist_ok=True)
        if name == "maya":
            write_default_workspace(folder_path)
        if subtree:
            build_folder_tree(folder_path, subtree)


def build_shot_task_structure(shot_path, tasks=None):
    """
    Create the standard task/subfolder tree inside a shot folder.

    2.24.20: tasks (optional) restricts this to a specific subset of
    SHOT_TASK_STRUCTURE's keys instead of building all of them — same
    reasoning as build_asset_task_structure's tasks param, for Export/
    Import Pipeline Package. Every existing caller omits this (defaults to
    None -> all tasks), so behavior is unchanged for them.
    """
    for task in (tasks if tasks is not None else SHOT_TASK_STRUCTURE.keys()):
        subtree = SHOT_TASK_STRUCTURE.get(task)
        if subtree is None:
            continue
        task_path = os.path.join(shot_path, task)
        os.makedirs(task_path, exist_ok=True)
        build_folder_tree(task_path, subtree)


def _create_shot_folders(prefix, scenes_dir, numbers):
    """
    Create one folder per shot number, building the standard task/software
    structure inside each (whether the shot folder is brand new or already
    existed, so re-running this always fills in anything missing).
    Returns (created, skipped) lists.
    """
    created = []
    skipped = []

    for number in numbers:
        shot_name = format_shot_name(prefix, number)
        shot_path = os.path.join(scenes_dir, shot_name)
        if os.path.isdir(shot_path):
            skipped.append(shot_name)
        else:
            os.makedirs(shot_path)
            created.append(shot_name)

        build_shot_task_structure(shot_path)

    print(f"Created {len(created)} shot folder(s) in: {scenes_dir}")
    for name in created:
        print(f"  {name}")
    if skipped:
        print(f"Skipped {len(skipped)} already-existing shot(s) (structure refreshed):")
        for name in skipped:
            print(f"  {name}")

    cmds.confirmDialog(
        title="Shots Created",
        message=(
            f"Created: {len(created)}\n"
            f"Already existed: {len(skipped)}\n\n"
            "See Script Editor output for details."
        ),
        button=["OK"],
    )


def set_shot_prefix():
    """Prompt for a new shot prefix and store it."""
    prefix = _prompt_for_name("Set Shot Prefix", "Shot Prefix (e.g. SH):")
    if not prefix:
        return

    cmds.optionVar(stringValue=(SHOT_PREFIX_OPTVAR, prefix))
    print(f"Shot prefix set to: {prefix}")
    cmds.confirmDialog(title="Shot Prefix Set", message=f"Shot prefix is now:\n{prefix}", button=["OK"])


def use_existing_shot_prefix():
    """Display the currently stored shot prefix."""
    prefix = get_shot_prefix()
    if not prefix:
        return

    cmds.confirmDialog(title="Current Shot Prefix", message=f"Current shot prefix:\n{prefix}", button=["OK"])


def set_range():
    """Create a fresh range of shot folders from a start to an end number."""
    prefix = get_shot_prefix()
    project_path = get_current_project()
    if not prefix or not project_path:
        return

    start = _prompt_for_int("Set Range", "Start Shot Number (e.g. 10):")
    if start is None:
        return
    end = _prompt_for_int("Set Range", "End Shot Number (e.g. 100):")
    if end is None:
        return

    if start > end:
        cmds.warning("Start number must be less than or equal to end number.")
        return

    numbers = list(range(start, end + 1, SHOT_NUMBER_STEP))
    scenes_dir = get_scenes_directory(project_path)
    _create_shot_folders(prefix, scenes_dir, numbers)


def extend_range():
    """Add more shots after the last existing shot for the current prefix."""
    prefix = get_shot_prefix()
    project_path = get_current_project()
    if not prefix or not project_path:
        return

    scenes_dir = get_scenes_directory(project_path)
    existing = get_existing_shot_numbers(scenes_dir, prefix)
    if not existing:
        cmds.warning('No existing shots found for this prefix. Use "Set Range" first.')
        return

    count = _prompt_for_int("Extend Range", "How many additional shots?")
    if count is None or count <= 0:
        return

    last_number = existing[-1]
    numbers = [last_number + (SHOT_NUMBER_STEP * i) for i in range(1, count + 1)]
    _create_shot_folders(prefix, scenes_dir, numbers)


def single_shot():
    """Create one specific shot folder by number."""
    prefix = get_shot_prefix()
    project_path = get_current_project()
    if not prefix or not project_path:
        return

    number = _prompt_for_int("Single Shot", "Shot Number (e.g. 15):")
    if number is None:
        return

    scenes_dir = get_scenes_directory(project_path)
    _create_shot_folders(prefix, scenes_dir, [number])


CREATE_SHOT_FOLDERS_WINDOW = "createShotFoldersWindow"


def show_create_shot_folders_window():
    """
    Option-box style window for shot creation: current project, shot
    prefix, a Start/End range, and a "Create Single Shot" toggle that
    swaps the range fields for a single shot number field instead.
    """
    project_path = get_current_project(warn_if_missing=False)

    current_prefix = get_shot_prefix(warn_if_missing=False) or "SH"

    if cmds.window(CREATE_SHOT_FOLDERS_WINDOW, exists=True):
        cmds.deleteUI(CREATE_SHOT_FOLDERS_WINDOW)

    window = cmds.window(CREATE_SHOT_FOLDERS_WINDOW, title="Create Shot Folders", sizeable=False, width=340)
    cmds.columnLayout(adjustableColumn=True, columnAlign="left", rowSpacing=6, columnOffset=("both", 12))

    cmds.text(label="")  # top spacer
    cmds.text(label="Create Shot Folders", font="boldLabelFont", align="left")
    cmds.separator(height=10, style="in")

    project_name = os.path.basename(project_path.rstrip(os.sep)) if project_path else ""
    cmds.rowLayout(numberOfColumns=2, columnWidth2=(90, 180), adjustableColumn=2)
    cmds.text(label="Project")
    project_field = cmds.textField(text=project_name, editable=not project_path)
    cmds.setParent("..")

    if not project_path:
        cmds.text(label="No current project set. Enter a project name first.", align="left")

    cmds.separator(height=10, style="in")

    cmds.rowLayout(numberOfColumns=2, columnWidth2=(90, 180), adjustableColumn=2)
    cmds.text(label="Shot Prefix")
    prefix_field = cmds.textField(text=current_prefix)
    cmds.setParent("..")

    cmds.separator(height=10, style="in")
    cmds.text(label="Range", font="boldLabelFont", align="left")

    range_mode_radio = cmds.radioButtonGrp(
        label="",
        labelArray2=("New Range", "Append Range"),
        numberOfRadioButtons=2,
        select=1,
        columnWidth3=(1, 130, 130),
    )

    increment_radio = cmds.radioButtonGrp(
        label="Increment",
        labelArray3=("1", "5", "10"),
        numberOfRadioButtons=3,
        select=3,
        columnWidth4=(70, 60, 60, 60),
    )

    cmds.rowLayout(numberOfColumns=2, columnWidth2=(90, 180), adjustableColumn=2)
    cmds.text(label="# of Shots")
    shots_count_field = cmds.textField(text="10")
    cmds.setParent("..")

    existing_shots_text = cmds.text(label="", align="left")

    cmds.separator(height=10, style="in")

    def zero_shot_exists(prefix):
        if not project_path:
            return False
        scene_dir = get_scenes_directory(project_path)
        zero_shot_name = format_shot_name(prefix, 0)
        return os.path.isdir(os.path.join(scene_dir, zero_shot_name))

    def get_selected_increment():
        return {1: 1, 2: 5, 3: 10}[cmds.radioButtonGrp(increment_radio, query=True, select=True)]

    def get_existing_numbers_for_prefix(prefix):
        if not project_path:
            return []
        scene_dir = get_scenes_directory(project_path)
        return get_existing_shot_numbers(scene_dir, prefix)

    def compute_shot_numbers(prefix, is_single):
        """Returns (numbers, error_message) — numbers already includes 0000 if that checkbox is on."""
        if is_single:
            number_text = cmds.textField(shot_number_field, query=True, text=True).strip()
            try:
                numbers = [int(number_text)]
            except ValueError:
                return None, f'"{number_text}" is not a valid shot number.'
        else:
            increment = get_selected_increment()
            is_append = cmds.radioButtonGrp(range_mode_radio, query=True, select=True) == 2
            if is_append:
                existing = get_existing_numbers_for_prefix(prefix)
                start = (max(existing) + increment) if existing else increment
            else:
                start = increment

            count_text = cmds.textField(shots_count_field, query=True, text=True).strip()
            try:
                count = int(count_text)
            except ValueError:
                return None, f'"{count_text}" is not a valid number of shots.'
            if count <= 0:
                return None, "Number of shots must be at least 1."

            numbers = [start + i * increment for i in range(count)]

        include_zero = cmds.checkBox(zero_shot_checkbox, query=True, value=True) and cmds.checkBox(
            zero_shot_checkbox, query=True, enable=True
        )
        if include_zero and 0 not in numbers:
            numbers = [0] + numbers

        return numbers, None

    def update_preview(*_args):
        prefix = cmds.textField(prefix_field, query=True, text=True).strip() or "SH"
        is_single = cmds.checkBox(single_checkbox, query=True, value=True)

        numbers, error = compute_shot_numbers(prefix, is_single)
        if error or not numbers:
            preview = "Creating: ____"
        elif len(numbers) == 1:
            preview = f"Creating: {format_shot_name(prefix, numbers[0])}"
        else:
            names = [format_shot_name(prefix, n) for n in numbers]
            if len(names) > 3:
                preview = f"Creating: {names[0]}, {names[1]} \u2192 {names[-1]} ({len(names)} shots)"
            else:
                preview = f"Creating: {', '.join(names)}"

        cmds.text(preview_text, edit=True, label=preview)

        # Live summary of what already exists for this prefix — shows the
        # range so a student knows where "Append Range" will continue from.
        existing = get_existing_numbers_for_prefix(prefix)
        if existing:
            first_name = format_shot_name(prefix, existing[0])
            last_name = format_shot_name(prefix, existing[-1])
            if len(existing) == 1:
                summary = f"Existing shots: {first_name} (1 shot)"
            else:
                summary = f"Existing shots: {first_name} \u2192 {last_name} ({len(existing)} shots)"
        elif project_path:
            summary = f'No shots exist yet for prefix "{prefix}".'
        else:
            summary = ""
        cmds.text(existing_shots_text, edit=True, label=summary)

        # Grey out the 0000 checkbox if that shot already exists for this prefix,
        # and keep its label in sync with the current prefix.
        already_exists = zero_shot_exists(prefix)
        zero_display_name = format_shot_name(prefix, 0)
        cmds.checkBox(
            zero_shot_checkbox,
            edit=True,
            label=f"Create {zero_display_name} by default",
            enable=not already_exists,
            value=True if already_exists else cmds.checkBox(zero_shot_checkbox, query=True, value=True),
        )

    def refresh_field_states(*_args):
        is_single = cmds.checkBox(single_checkbox, query=True, value=True)

        cmds.textField(shot_number_field, edit=True, enable=is_single)
        cmds.radioButtonGrp(range_mode_radio, edit=True, enable=not is_single)
        cmds.radioButtonGrp(increment_radio, edit=True, enable=not is_single)
        cmds.textField(shots_count_field, edit=True, enable=not is_single)

        update_preview()

    single_checkbox = cmds.checkBox(label="Create Single Shot", value=False, changeCommand=refresh_field_states)

    cmds.rowLayout(numberOfColumns=2, columnWidth2=(90, 180), adjustableColumn=2)
    cmds.text(label="Shot Number")
    shot_number_field = cmds.textField(text="", enable=False)
    cmds.setParent("..")

    cmds.separator(height=10, style="in")

    zero_shot_checkbox = cmds.checkBox(
        label=f"Create {current_prefix}0000 by default",
        value=zero_shot_exists(current_prefix),
        changeCommand=lambda *a: update_preview(),
    )

    cmds.separator(height=10, style="in")

    preview_text = cmds.text(label="", align="left")

    cmds.radioButtonGrp(range_mode_radio, edit=True, changeCommand=refresh_field_states)
    cmds.radioButtonGrp(increment_radio, edit=True, changeCommand=refresh_field_states)
    cmds.textField(prefix_field, edit=True, textChangedCommand=refresh_field_states)
    cmds.textField(shots_count_field, edit=True, textChangedCommand=update_preview)
    cmds.textField(shot_number_field, edit=True, textChangedCommand=update_preview)
    refresh_field_states()

    cmds.separator(height=10, style="in")

    def on_create(*_args):
        current_project_path = get_current_project(warn_if_missing=False)

        if not current_project_path:
            typed_name = cmds.textField(project_field, query=True, text=True).strip()
            if not typed_name:
                cmds.warning("Enter a project name first.")
                return

            parent_result = cmds.fileDialog2(fileMode=3, caption="Select Location for New Project")
            if not parent_result:
                return

            current_project_path = os.path.join(parent_result[0], typed_name)
            if os.path.isdir(current_project_path):
                cmds.warning(f"Folder already exists: {current_project_path}")
                return

            build_project_skeleton(current_project_path)
            print(f"Created project folder: {current_project_path}")

        prefix = cmds.textField(prefix_field, query=True, text=True).strip()
        if not prefix:
            cmds.warning("Shot prefix cannot be empty.")
            return
        cmds.optionVar(stringValue=(SHOT_PREFIX_OPTVAR, prefix))

        is_single = cmds.checkBox(single_checkbox, query=True, value=True)
        numbers, error = compute_shot_numbers(prefix, is_single)
        if error:
            cmds.warning(error)
            return

        cmds.deleteUI(window)

        target_scenes_dir = get_scenes_directory(current_project_path)
        _create_shot_folders(prefix, target_scenes_dir, numbers)

    cmds.columnLayout(adjustableColumn=True, columnAlign="center")
    cmds.rowLayout(numberOfColumns=2, columnAttach2=("both", "both"), columnOffset2=(0, 8))
    cmds.button(label="Create", width=85, command=on_create)
    cmds.button(label="Cancel", width=85, command=lambda *a: cmds.deleteUI(window))
    cmds.setParent("..")
    cmds.setParent("..")

    cmds.text(label="")  # bottom spacer

    cmds.showWindow(window)


# ------------------------------------------------------------------
# Data Manager — Create Custom Folder
# ------------------------------------------------------------------

CREATE_CUSTOM_FOLDER_WINDOW = "createCustomFolderWindow"

CUSTOM_FOLDER_CATEGORY_PROJECT = "Project"
CUSTOM_FOLDER_CATEGORY_ASSET = "Asset"
CUSTOM_FOLDER_CATEGORY_SHOT = "Shot"
CUSTOM_FOLDER_CATEGORIES = (
    CUSTOM_FOLDER_CATEGORY_PROJECT,
    CUSTOM_FOLDER_CATEGORY_ASSET,
    CUSTOM_FOLDER_CATEGORY_SHOT,
)

CUSTOM_FOLDER_ALL_LABEL = "All"
CUSTOM_FOLDER_ROOT_LABEL = "Root"


def show_create_custom_folder_window():
    """
    "Create Custom Folder": pick a category (Project/Asset/Shot), then a
    specific one of those (or "All" of them), then Root or a specific task
    subfolder (task dropdown is disabled/inert for Project — a project has
    no task subfolders, it's shown only for visual consistency with
    Asset/Shot), then type a folder name and create it.

    Dropdown-row layout modeled on Add Asset's tight columnAttach row;
    Create/Cancel buttons match Create Shot Folders' / Create New Project's
    style.
    """
    if cmds.window(CREATE_CUSTOM_FOLDER_WINDOW, exists=True):
        cmds.deleteUI(CREATE_CUSTOM_FOLDER_WINDOW)

    project_path = get_current_project()
    if not project_path:
        return

    window = cmds.window(CREATE_CUSTOM_FOLDER_WINDOW, title="Create Custom Folder", sizeable=False, width=420)
    cmds.columnLayout(adjustableColumn=True, columnAlign="left", rowSpacing=6, columnOffset=("both", 12))

    cmds.text(label="")  # top spacer
    cmds.text(label="Create Custom Folder", font="boldLabelFont", align="left")
    cmds.separator(height=10, style="in")

    asset_task_choices = [(ASSET_MANAGER_TASK_LABELS[t], t) for t in ASSET_MANAGER_TASK_ORDER]
    shot_task_choices = [(t.capitalize(), t) for t in SHOT_TASK_STRUCTURE.keys()]

    projects_root = get_projects_root()
    available_projects = scan_projects_root(projects_root) if projects_root else []
    project_lookup = {os.path.basename(p.rstrip(os.sep)): p for p in available_projects}

    # Category / specific-target / task dropdowns all in one row, sitting
    # close together — same columnAttachN/columnOffsetN technique as Add
    # Asset (no columnWidth cells, which leave dead space when a
    # dropdown's rendered size is smaller than its assigned column).
    cmds.rowLayout(
        numberOfColumns=3,
        columnAttach3=("left", "left", "left"),
        columnOffset3=(0, 8, 8),
    )
    category_dropdown = cmds.optionMenu(width=90)
    for category in CUSTOM_FOLDER_CATEGORIES:
        cmds.menuItem(label=category, parent=category_dropdown)
    target_dropdown = cmds.optionMenu(width=150)
    task_dropdown = cmds.optionMenu(width=110)
    cmds.setParent("..")

    task_lookup = {}  # display label -> actual task folder name, for the current category

    def refresh_tasks(*_args):
        for item in cmds.optionMenu(task_dropdown, query=True, itemListLong=True) or []:
            cmds.deleteUI(item)
        task_lookup.clear()

        category = cmds.optionMenu(category_dropdown, query=True, value=True)
        cmds.menuItem(label=CUSTOM_FOLDER_ROOT_LABEL, parent=task_dropdown)

        if category == CUSTOM_FOLDER_CATEGORY_ASSET:
            for label, task_name in asset_task_choices:
                task_lookup[label] = task_name
                cmds.menuItem(label=label, parent=task_dropdown)
        elif category == CUSTOM_FOLDER_CATEGORY_SHOT:
            for label, task_name in shot_task_choices:
                task_lookup[label] = task_name
                cmds.menuItem(label=label, parent=task_dropdown)

        # Project has no task subfolders of its own — the dropdown stays
        # on "Root" and is disabled outright (present only so all three
        # categories look consistent; per Todd it doesn't function for Project).
        cmds.optionMenu(
            task_dropdown, edit=True, value=CUSTOM_FOLDER_ROOT_LABEL, enable=(category != CUSTOM_FOLDER_CATEGORY_PROJECT)
        )

    def refresh_targets(*_args):
        for item in cmds.optionMenu(target_dropdown, query=True, itemListLong=True) or []:
            cmds.deleteUI(item)

        category = cmds.optionMenu(category_dropdown, query=True, value=True)
        cmds.menuItem(label=CUSTOM_FOLDER_ALL_LABEL, parent=target_dropdown)

        if category == CUSTOM_FOLDER_CATEGORY_PROJECT:
            for name in sorted(project_lookup.keys()):
                cmds.menuItem(label=name, parent=target_dropdown)
        elif category == CUSTOM_FOLDER_CATEGORY_ASSET:
            for asset_name, _asset_dir in list_all_assets(project_path):
                cmds.menuItem(label=asset_name, parent=target_dropdown)
        else:  # Shot
            for shot_name in list_existing_shots(project_path):
                cmds.menuItem(label=shot_name, parent=target_dropdown)

        refresh_tasks()

    cmds.optionMenu(category_dropdown, edit=True, changeCommand=refresh_targets)
    refresh_targets()

    cmds.separator(height=10, style="in")

    cmds.rowLayout(numberOfColumns=2, columnWidth2=(90, 180), adjustableColumn=2)
    cmds.text(label="Folder Name")
    name_field = cmds.textField(text="")
    cmds.setParent("..")

    cmds.separator(height=10, style="in")

    def on_create(*_args):
        folder_name = (cmds.textField(name_field, query=True, text=True) or "").strip()
        if not folder_name:
            cmds.warning("Enter a folder name first.")
            return
        if "/" in folder_name or "\\" in folder_name:
            cmds.warning("Folder name can't contain slashes.")
            return

        category = cmds.optionMenu(category_dropdown, query=True, value=True)
        target = cmds.optionMenu(target_dropdown, query=True, value=True)
        task_label = cmds.optionMenu(task_dropdown, query=True, value=True)
        task_name = task_lookup.get(task_label)  # None means Root

        # (label, base_dir) pairs — folder_name gets created inside each base_dir.
        base_dirs = []

        if category == CUSTOM_FOLDER_CATEGORY_PROJECT:
            if target == CUSTOM_FOLDER_ALL_LABEL:
                base_dirs = list(project_lookup.items())
            elif target in project_lookup:
                base_dirs = [(target, project_lookup[target])]

        elif category == CUSTOM_FOLDER_CATEGORY_ASSET:
            all_assets = list_all_assets(project_path)
            if target == CUSTOM_FOLDER_ALL_LABEL:
                candidates = all_assets
            else:
                candidates = [(n, p) for n, p in all_assets if n == target]
            for asset_name, asset_dir in candidates:
                base_dir = os.path.join(asset_dir, task_name) if task_name else asset_dir
                base_dirs.append((asset_name, base_dir))

        else:  # Shot
            shots_dir = os.path.join(project_path, "shots")
            all_shots = list_existing_shots(project_path)
            candidates = all_shots if target == CUSTOM_FOLDER_ALL_LABEL else [n for n in all_shots if n == target]
            for shot_name in candidates:
                shot_dir = os.path.join(shots_dir, shot_name)
                base_dir = os.path.join(shot_dir, task_name) if task_name else shot_dir
                base_dirs.append((shot_name, base_dir))

        if not base_dirs:
            cmds.warning("Nothing to create the folder in — check your selections.")
            return

        created = []
        skipped = []
        for label, base_dir in base_dirs:
            new_folder = os.path.join(base_dir, folder_name)
            if os.path.isdir(new_folder):
                skipped.append(label)
                continue
            os.makedirs(new_folder, exist_ok=True)
            created.append(label)

        print(
            f'Create Custom Folder "{folder_name}": created in {len(created)}, '
            f"skipped {len(skipped)} (already existed)."
        )
        for label in created:
            print(f"  created: {label}")
        for label in skipped:
            print(f"  already existed: {label}")

        cmds.deleteUI(window)
        cmds.confirmDialog(
            title="Custom Folder Created",
            message=(
                f'"{folder_name}" created in {len(created)} location(s).\n'
                f"Already existed in {len(skipped)} location(s)."
            ),
            button=["OK"],
        )

    cmds.columnLayout(adjustableColumn=True, columnAlign="center")
    cmds.rowLayout(numberOfColumns=2, columnAttach2=("both", "both"), columnOffset2=(0, 8))
    cmds.button(label="Create", width=85, command=on_create)
    cmds.button(label="Cancel", width=85, command=lambda *a: cmds.deleteUI(window))
    cmds.setParent("..")
    cmds.setParent("..")

    cmds.text(label="")  # bottom spacer

    cmds.showWindow(window)


# ============================================================
# PROJECT SETTINGS
# ============================================================

def _prompt_for_float(title, message):
    """Show a text-entry dialog and return a float, or None if cancelled/invalid."""
    result = cmds.promptDialog(
        title=title,
        message=message,
        button=["OK", "Cancel"],
        defaultButton="OK",
        cancelButton="Cancel",
        dismissString="Cancel",
    )
    if result != "OK":
        return None

    text = cmds.promptDialog(query=True, text=True).strip()
    try:
        return float(text)
    except ValueError:
        cmds.warning(f'"{text}" is not a valid number.')
        return None


def get_current_output_size():
    width = cmds.getAttr("defaultResolution.width")
    height = cmds.getAttr("defaultResolution.height")
    return width, height


def set_scene_output_size(width, height):
    cmds.setAttr("defaultResolution.width", width)
    cmds.setAttr("defaultResolution.height", height)


def get_current_start_frame():
    return int(cmds.playbackOptions(query=True, animationStartTime=True))


def set_scene_start_frame(frame):
    cmds.playbackOptions(minTime=frame, animationStartTime=frame)


def set_scene_end_frame(frame):
    cmds.playbackOptions(maxTime=frame, animationEndTime=frame)


def output_size_settings():
    """Show the current output (render resolution) size and let the student keep it or change it."""
    width, height = get_current_output_size()

    result = cmds.confirmDialog(
        title="Output Size",
        message=f"Current output size: {width} x {height}\n\nKeep this size, or change it?",
        button=["Keep", "Change", "Cancel"],
        defaultButton="Keep",
        cancelButton="Cancel",
        dismissString="Cancel",
    )
    if result == "Cancel":
        return

    if result == "Change":
        new_width = _prompt_for_int("Change Output Size", "Width (e.g. 1920):")
        if new_width is None:
            return
        new_height = _prompt_for_int("Change Output Size", "Height (e.g. 1080):")
        if new_height is None:
            return
        width, height = new_width, new_height
        set_scene_output_size(width, height)

    cmds.optionVar(intValue=(OUTPUT_WIDTH_OPTVAR, width))
    cmds.optionVar(intValue=(OUTPUT_HEIGHT_OPTVAR, height))
    print(f"Project output size saved: {width} x {height}")
    cmds.confirmDialog(
        title="Output Size Saved",
        message=f"Output size saved as: {width} x {height}",
        button=["OK"],
    )


def start_frame_settings():
    """Show the current starting frame and let the student keep it or change it."""
    current = get_current_start_frame()

    result = cmds.confirmDialog(
        title="Starting Frame Number",
        message=f"Current starting frame: {current}\n\nKeep this starting frame, or change it?",
        button=["Keep", "Change", "Cancel"],
        defaultButton="Keep",
        cancelButton="Cancel",
        dismissString="Cancel",
    )
    if result == "Cancel":
        return

    if result == "Change":
        new_start = _prompt_for_int("Change Starting Frame", "Starting Frame (e.g. 1001):")
        if new_start is None:
            return
        current = new_start
        set_scene_start_frame(current)

    cmds.optionVar(intValue=(START_FRAME_OPTVAR, current))
    print(f"Project starting frame saved: {current}")
    cmds.confirmDialog(
        title="Starting Frame Saved",
        message=f"Starting frame saved as: {current}",
        button=["OK"],
    )


def apply_saved_settings(*_args):
    """Apply whichever project settings have been saved to the current scene. Returns a list of what was applied."""
    applied = []

    if cmds.optionVar(exists=OUTPUT_WIDTH_OPTVAR) and cmds.optionVar(exists=OUTPUT_HEIGHT_OPTVAR):
        width = cmds.optionVar(query=OUTPUT_WIDTH_OPTVAR)
        height = cmds.optionVar(query=OUTPUT_HEIGHT_OPTVAR)
        set_scene_output_size(width, height)
        applied.append(f"Output Size: {width} x {height}")

    if cmds.optionVar(exists=START_FRAME_OPTVAR):
        start_frame = cmds.optionVar(query=START_FRAME_OPTVAR)
        set_scene_start_frame(start_frame)
        applied.append(f"Starting Frame: {start_frame}")

    if cmds.optionVar(exists=END_FRAME_OPTVAR):
        end_frame = cmds.optionVar(query=END_FRAME_OPTVAR)
        set_scene_end_frame(end_frame)
        applied.append(f"Ending Frame: {end_frame}")

    # Always align Maya's workspace to whatever project/asset this scene
    # belongs to, regardless of whether any other settings were saved —
    # this is what makes a freshly-opened scene "recognize" its project.
    align_maya_project()

    if applied:
        print("Applied saved project settings:")
        for line in applied:
            print(f"  {line}")
    else:
        print("No project settings have been saved yet.")

    return applied


def run_project_settings():
    """Manually apply all saved project settings (output size, start frame) to the current scene."""
    applied = apply_saved_settings()
    if not applied:
        cmds.warning("No project settings have been saved yet (Output Size / Starting Frame Number).")
        return

    cmds.confirmDialog(
        title="Project Settings Applied",
        message="Applied:\n" + "\n".join(applied),
        button=["OK"],
    )


def register_scene_opened_job():
    """
    Register a scriptJob so saved project settings auto-apply whenever a
    scene is opened. Cleans up any prior job from an earlier run of this
    script first, so re-running it doesn't stack duplicate jobs.
    """
    for job_str in cmds.scriptJob(listJobs=True):
        if "apply_saved_settings" in job_str and "SceneOpened" in job_str:
            job_id = int(job_str.split(":")[0])
            try:
                cmds.scriptJob(kill=job_id, force=True)
            except Exception:
                pass

    cmds.scriptJob(event=["SceneOpened", apply_saved_settings], protected=True)


# ============================================================
# RENDER SETTINGS
# ============================================================

def customize_render_frame_range():
    """Prompt for a custom render frame range override. Apply Settings uses this instead of the time slider if set."""
    start = _prompt_for_int("Render Frame Range", "Start Frame:")
    if start is None:
        return
    end = _prompt_for_int("Render Frame Range", "End Frame:")
    if end is None:
        return
    if start > end:
        cmds.warning("Start frame must be less than or equal to end frame.")
        return

    cmds.optionVar(intValue=(RENDER_FRAME_START_OPTVAR, start))
    cmds.optionVar(intValue=(RENDER_FRAME_END_OPTVAR, end))
    print(f"Render frame range set to: {start} - {end}")
    cmds.confirmDialog(
        title="Render Frame Range Set",
        message=f"Render frame range set to:\n{start} - {end}",
        button=["OK"],
    )


def apply_render_settings():
    """
    Configure Arnold render settings:
      - Output path: <Scene>_<RenderLayer>/<Version>/<RenderPass>/<Scene>_<RenderLayer>_<RenderPass>
        (relative to the workspace's "images" rule, which now always
        resolves to <task>/output/render/ — see DEFAULT_WORKSPACE_MEL —
        so no leading "render/" segment here, that would double it up)
      - Resolution: saved Project Settings value, or 1920x1080 default
      - Frame range: saved Customize override, or match the time slider
      - Output format: name.#.ext
      - Half precision, autocrop, and merge AOVs all enabled
    """
    # Output path / file naming
    cmds.setAttr(
        "defaultRenderGlobals.imageFilePrefix",
        "<Scene>_<RenderLayer>/<Version>/<RenderPass>/<Scene>_<RenderLayer>_<RenderPass>",
        type="string",
    )

    # Output resolution: saved Project Settings value, else a default.
    if cmds.optionVar(exists=OUTPUT_WIDTH_OPTVAR) and cmds.optionVar(exists=OUTPUT_HEIGHT_OPTVAR):
        width = cmds.optionVar(query=OUTPUT_WIDTH_OPTVAR)
        height = cmds.optionVar(query=OUTPUT_HEIGHT_OPTVAR)
    else:
        width, height = 1920, 1080
    set_scene_output_size(width, height)

    # Frame range: saved Customize override, else match the time slider.
    if cmds.optionVar(exists=RENDER_FRAME_START_OPTVAR) and cmds.optionVar(exists=RENDER_FRAME_END_OPTVAR):
        start_frame = cmds.optionVar(query=RENDER_FRAME_START_OPTVAR)
        end_frame = cmds.optionVar(query=RENDER_FRAME_END_OPTVAR)
    else:
        start_frame = int(cmds.playbackOptions(query=True, minTime=True))
        end_frame = int(cmds.playbackOptions(query=True, maxTime=True))

    cmds.setAttr("defaultRenderGlobals.animation", 1)
    cmds.setAttr("defaultRenderGlobals.animationRange", 0)  # explicit Start/End, not "time slider" live-linked
    cmds.setAttr("defaultRenderGlobals.startFrame", start_frame)
    cmds.setAttr("defaultRenderGlobals.endFrame", end_frame)
    cmds.setAttr("defaultRenderGlobals.byFrameStep", 1)

    # Output format: name.#.ext
    cmds.setAttr("defaultRenderGlobals.outFormatControl", 2)
    cmds.setAttr("defaultRenderGlobals.putFrameBeforeExt", 1)
    cmds.setAttr("defaultRenderGlobals.extensionPadding", 4)

    # Arnold EXR driver options.
    try:
        cmds.setAttr("defaultArnoldDriver.halfPrecision", 1)
        cmds.setAttr("defaultArnoldDriver.autocrop", 1)
        cmds.setAttr("defaultArnoldDriver.mergeAOVs", 1)
    except Exception as e:
        cmds.warning(f"Could not set Arnold driver options (is Arnold loaded?): {e}")

    summary = (
        "Output path: <Scene>_<RenderLayer>/<Version>/<RenderPass>/<Scene>_<RenderLayer>_<RenderPass>\n"
        "(inside <task>/output/render/)\n"
        f"Resolution: {width} x {height}\n"
        f"Frame range: {start_frame} - {end_frame}\n"
        "Output format: name.#.ext\n"
        "Half precision, autocrop, and merge AOVs: on"
    )
    print("Render settings applied:")
    print(f"  {summary}".replace(chr(10), chr(10) + "  "))

    cmds.confirmDialog(title="Render Settings Applied", message=summary, button=["OK"])


# ------------------------------------------------------------------
# Lighting / Rendering — Scene Setup
# ------------------------------------------------------------------

LIGHT_SUBGROUP_NAMES = ["_rim", "_env", "_fill", "_key", "_shadow", "_volume"]
OBJECT_SUBGROUP_NAMES = ["_char", "_set", "_prop"]
OVERRIDE_SET_NAMES = ["_char_override", "_prop_override", "_set_override"]


def _create_empty_group(name, parent=None):
    """Create an empty transform group with this name if it doesn't already exist. Returns the node's name."""
    if cmds.objExists(name):
        return name
    grp = cmds.group(empty=True, name=name)
    if parent:
        grp = cmds.parent(grp, parent)[0]
    return grp


def _add_arnold_override_attrs(set_name):
    """
    Add the same override attributes Arnold's 'Add Arnold Attributes' page
    adds — primaryVisibility and aiMatte — directly on a set node, so the
    set can be used as an Arnold attribute-override container.
    primaryVisibility defaults to on; aiMatte defaults to off.
    """
    for attr_name, default_value in (("primaryVisibility", True), ("aiMatte", False)):
        if not cmds.attributeQuery(attr_name, node=set_name, exists=True):
            cmds.addAttr(set_name, longName=attr_name, attributeType="bool")
            cmds.setAttr(f"{set_name}.{attr_name}", keyable=True)
            cmds.setAttr(f"{set_name}.{attr_name}", default_value)


OVERRIDE_SET_TO_OBJECT_GROUP = {
    "_char_override": "_char",
    "_prop_override": "_prop",
    "_set_override": "_set",
}


def scene_setup():
    """
    Build the standard lighting scene setup: empty groups for the render
    camera, lights (with 6 sub-groups), objects (with 3 sub-groups), an
    unused group (hidden by default), and 3 override sets (each containing
    its matching object group and Arnold override attributes) under an
    _overrides set. Safe to run more than once — anything already there
    is left alone.
    """
    _create_empty_group("_rendercamera")

    lights_grp = _create_empty_group("_lights")
    for name in LIGHT_SUBGROUP_NAMES:
        _create_empty_group(name, parent=lights_grp)

    objects_grp = _create_empty_group("_objects")
    for name in OBJECT_SUBGROUP_NAMES:
        _create_empty_group(name, parent=objects_grp)

    unused_grp = _create_empty_group("_unused")
    cmds.setAttr(f"{unused_grp}.visibility", 0)

    for set_name in OVERRIDE_SET_NAMES:
        if not cmds.objExists(set_name):
            cmds.sets(name=set_name, empty=True)

        obj_group = OVERRIDE_SET_TO_OBJECT_GROUP.get(set_name)
        if obj_group and cmds.objExists(obj_group):
            if not cmds.sets(obj_group, isMember=set_name):
                cmds.sets(obj_group, add=set_name)

        _add_arnold_override_attrs(set_name)

    if not cmds.objExists("_overrides"):
        cmds.sets(OVERRIDE_SET_NAMES, name="_overrides")

    print("Scene setup created/verified: _rendercamera, _lights (+6), _objects (+3), _unused (hidden), _overrides (+3 sets)")
    cmds.confirmDialog(
        title="Scene Setup Created",
        message=(
            "Created:\n"
            "_rendercamera\n"
            "_lights (rim, env, fill, key, shadow, volume)\n"
            "_objects (char, set, prop)\n"
            "_unused (hidden)\n"
            "_overrides set (char/prop/set overrides, each with their object group\n"
            "and primaryVisibility/aiMatte attributes)"
        ),
        button=["OK"],
    )


# ------------------------------------------------------------------
# Lighting / Rendering — Create AOVs + Render Layers
# ------------------------------------------------------------------
# Combined as of 2.29.0: this used to be two separate menu items
# ("Create AOVs" and "Add/Update Render Layers"). Now a single "Create
# AOVs" window always creates the selected AOVs AND builds/updates the
# "beauty_All" render layer (the old add_render_layers() behavior,
# folded in on every Apply). A new "Create Utility render layer"
# checkbox, offered only when utility_All doesn't exist yet, additionally
# builds a "utility_All" layer whose lights collection is disabled and
# whose AOV set is the mirror image of beauty_All's (per-layer AOV
# enable/disable via Render Setup overrides on each aiAOV node's
# .enabled attribute).

BEAUTY_AOVS_ON = ["albedo", "diffuse", "specular", "emission", "sss"]
BEAUTY_AOVS_OFF = ["coat", "diffuse_indirect", "specular_indirect", "transmission", "transmission_indirect"]
UTILITY_AOVS_ON = ["Z", "motionvector", "crypto_asset", "crypto_material", "crypto_object"]
UTILITY_AOVS_OFF = ["N"]

RENDER_LAYER_LIGHT_GROUPS = ["_rim", "_env", "_fill", "_key"]

CREATE_AOVS_WINDOW = "createAOVsWindow"


def _ensure_arnold_render_options():
    """
    Make sure Arnold's render-options node (and its dynamic .aovs
    attribute) actually exists before touching AOVs.

    On a scene where Arnold hasn't been set as the current renderer
    (or Render Settings has never been opened with Arnold selected),
    defaultArnoldRenderOptions doesn't have its .aovs attribute yet,
    and mtoa's AOVInterface.addAOV()/removeAOV() fail with
    'No object matches name: defaultArnoldRenderOptions.aovs'. Setting
    the current renderer to arnold and calling mtoa.core.createOptions()
    forces mtoa to fully initialize that node first.
    """
    try:
        if cmds.getAttr("defaultRenderGlobals.currentRenderer") != "arnold":
            cmds.setAttr("defaultRenderGlobals.currentRenderer", "arnold", type="string")
        import mtoa.core as core
        core.createOptions()
    except Exception as e:
        cmds.warning(f"Could not initialize Arnold render options: {e}")


def create_aovs(beauty_selected, utility_selected, rgba_selected):
    """Create and activate each selected AOV via Arnold's AOV interface."""
    try:
        import mtoa.aovs as aovs
    except Exception as e:
        cmds.warning(f"Could not import mtoa.aovs (is Arnold loaded?): {e}")
        return [], []

    _ensure_arnold_render_options()

    interface = aovs.AOVInterface()
    created = []
    failed = []

    for aov_name in beauty_selected + utility_selected:
        try:
            if not interface.getAOVNode(aov_name):
                interface.addAOV(aov_name)
            created.append(aov_name)
        except Exception as e:
            failed.append((aov_name, str(e)))

    if rgba_selected:
        try:
            if not interface.getAOVNode("RGBA"):
                interface.addAOV("RGBA", aovType="rgba")
            created.append("RGBA")

            aov_node = "aiAOV_RGBA"
            if cmds.objExists(aov_node):
                try:
                    cmds.setAttr(f"{aov_node}.lightGroups", 1)
                except Exception as e:
                    cmds.warning(
                        f'Created RGBA AOV, but could not set "All Light Groups" on '
                        f'{aov_node}.lightGroups: {e}. Please verify/enable it manually in the '
                        "Attribute Editor."
                    )
                try:
                    cmds.setAttr(f"{aov_node}.globalAov", 0)
                except Exception as e:
                    cmds.warning(
                        f'Created RGBA AOV, but could not uncheck "Global AOV" on '
                        f'{aov_node}.globalAov: {e}. Please verify/disable it manually in the '
                        "Attribute Editor."
                    )
        except Exception as e:
            failed.append(("RGBA", str(e)))

    print(f"Created/verified {len(created)} AOV(s): {', '.join(created)}")
    if failed:
        print(f"{len(failed)} AOV(s) failed:")
        for name, err in failed:
            print(f"  {name}: {err}")

    return created, failed


def _aov_exists(aov_name):
    """Whether this AOV has already been created in the scene (its aiAOV_<name> node exists)."""
    return cmds.objExists(f"aiAOV_{aov_name}")


def _initial_aov_checkbox_states(beauty_layer_exists):
    """
    Returns (beauty_state, utility_state, rgba_state): {name: bool}
    dicts (rgba_state is just a bool) for seeding the checkboxes.

    On a first run (no beauty_All yet) these are the hardcoded
    BEAUTY/UTILITY_AOVS_ON/OFF defaults, same as before 2.29.0. Once
    beauty_All exists, they instead reflect which AOVs are already
    created in the scene, so reopening this window to add/update AOVs
    or render layers doesn't reset your previous choices.
    """
    if beauty_layer_exists:
        beauty_state = {name: _aov_exists(name) for name in BEAUTY_AOVS_ON + BEAUTY_AOVS_OFF}
        utility_state = {name: _aov_exists(name) for name in UTILITY_AOVS_ON + UTILITY_AOVS_OFF}
        rgba_state = _aov_exists("RGBA")
    else:
        beauty_state = {name: True for name in BEAUTY_AOVS_ON}
        beauty_state.update({name: False for name in BEAUTY_AOVS_OFF})
        utility_state = {name: True for name in UTILITY_AOVS_ON}
        utility_state.update({name: False for name in UTILITY_AOVS_OFF})
        rgba_state = True

    return beauty_state, utility_state, rgba_state


def _build_aov_columns(on_names, off_names, state):
    """Build two side-by-side columns of checkboxes, seeded from `state` ({name: bool})."""
    checkboxes = {}

    cmds.rowLayout(numberOfColumns=2, columnWidth2=(140, 140), columnAlign2=("left", "left"))

    cmds.columnLayout(adjustableColumn=True)
    for aov_name in on_names:
        checkboxes[aov_name] = cmds.checkBox(label=aov_name, value=state.get(aov_name, True))
    cmds.setParent("..")

    cmds.columnLayout(adjustableColumn=True)
    for aov_name in off_names:
        checkboxes[aov_name] = cmds.checkBox(label=aov_name, value=state.get(aov_name, False))
    cmds.setParent("..")

    cmds.setParent("..")
    return checkboxes


def _import_render_setup_modules():
    """Import and return (renderSetupModule, selectorModule), or (None, None) with a cmds.warning on failure."""
    try:
        import maya.app.renderSetup.model.renderSetup as renderSetupModule
        import maya.app.renderSetup.model.selector as selectorModule
        return renderSetupModule, selectorModule
    except Exception as e:
        cmds.warning(f"Could not import the Render Setup API: {e}")
        return None, None


def _get_render_layer(name):
    """Return the named Render Setup layer if it already exists, else None."""
    renderSetupModule, _ = _import_render_setup_modules()
    if renderSetupModule is None:
        return None
    rs = renderSetupModule.instance()
    try:
        return rs.getRenderLayer(name)
    except Exception:
        return None


def _configure_render_setup_prefs():
    """Turn off the "Enable untitled collections" and "Include all lights" global Render Setup prefs."""
    try:
        cmds.optionVar(intValue=("renderSetup_useUntitledCollections", 0))
    except Exception as e:
        cmds.warning(f'Could not disable "Enable untitled collections": {e}')
    try:
        cmds.optionVar(intValue=("renderSetup_includeAllLights", 0))
    except Exception as e:
        cmds.warning(f'Could not disable "Include all lights": {e}')


def _find_or_create_collection(layer, base_name):
    """
    Find this layer's collection named `base_name` (or an auto-suffixed
    variant like "objects1", "objects2" ...) and reuse it; create one if
    none exists.

    Why the suffix matters (bug found 2026-08-27): Render Setup collection
    node names must be unique scene-wide, not just per layer. beauty_All's
    "objects"/"lights" collections claim those literal names, so
    layer.createCollection("objects") on utility_All silently comes back
    named "objects1" instead. The old exact-name lookup
    (existing_collections.get("objects")) never matched that, so every
    Apply thought no "objects" collection existed yet and created a fresh
    one — which itself got suffixed one higher each time (objects1,
    objects2, objects3, ...), stacking up duplicates on utility_All.

    Matches by prefix + optional trailing digits instead, and — since
    that duplication already happened in the field — cleans up by
    deleting every extra match beyond the first (oldest) one, via the
    documented module-level collection.delete() (not raw cmds.delete(),
    per the lesson from the AOVCollection/render-layer deletion mistakes
    elsewhere in this file).
    """
    import maya.app.renderSetup.model.collection as collectionModule

    pattern = re.compile(rf"^{re.escape(base_name)}\d*$")
    candidates = sorted(
        (c for c in layer.getCollections() if pattern.match(c.name())),
        key=lambda c: c.name(),
    )
    if not candidates:
        return layer.createCollection(base_name)

    keep = candidates[0]
    for dupe in candidates[1:]:
        try:
            collectionModule.delete(dupe)
        except Exception as e:
            cmds.warning(f'Could not remove duplicate collection "{dupe.name()}" on {layer.name()}: {e}')
    return keep


def _build_objects_and_lights_collections(layer, selectorModule, disable_lights=False):
    """
    Add/update the standard "objects" (3 override sets, Sets filter) and
    "lights" (rim/env/fill/key groups) collections on a render layer.
    Returns (override_members, missing_overrides, light_members, missing_lights).

    If disable_lights is True, the "lights" collection is still created
    (so it's visible/re-enableable in the Render Setup panel) but its
    Render Setup "enabled" toggle is switched off — used for utility_All,
    which doesn't need light-group isolation.
    """
    objects_collection = _find_or_create_collection(layer, "objects")
    objects_selector = objects_collection.getSelector()
    try:
        objects_selector.setFilterType(selectorModule.Filters.kSets)
    except Exception as e:
        cmds.warning(f'Could not set "objects" collection filter to Sets on {layer.name()}: {e}')

    override_members = [name for name in OVERRIDE_SET_NAMES if cmds.objExists(name)]
    missing_overrides = [name for name in OVERRIDE_SET_NAMES if name not in override_members]
    try:
        objects_selector.staticSelection.set(override_members)
    except Exception as e:
        cmds.warning(f'Could not add override sets to "objects" collection on {layer.name()}: {e}')

    lights_collection = _find_or_create_collection(layer, "lights")
    lights_selector = lights_collection.getSelector()

    light_members = [name for name in RENDER_LAYER_LIGHT_GROUPS if cmds.objExists(name)]
    missing_lights = [name for name in RENDER_LAYER_LIGHT_GROUPS if name not in light_members]
    try:
        lights_selector.staticSelection.set(light_members)
    except Exception as e:
        cmds.warning(f'Could not add light groups to "lights" collection on {layer.name()}: {e}')

    try:
        # NOT setEnabled() — Collection has no such method (confirmed via
        # dir(): 'Collection' object has no attribute 'setEnabled', caught
        # silently by this try/except every single Apply, which is why
        # utility_All's "lights" collection never actually disabled
        # despite reporting no error). The real setter is setSelfEnabled();
        # isEnabled() reflects the propagated (self AND parent-chain)
        # state, which is what actually drives the Render Setup UI/render.
        lights_collection.setSelfEnabled(not disable_lights)
    except Exception as e:
        cmds.warning(f'Could not set "lights" collection enabled state on {layer.name()}: {e}')

    return override_members, missing_overrides, light_members, missing_lights


def _set_layer_aov_enabled(layer, aov_names, enabled):
    """
    Force each aiAOV_<name> node's .enabled attribute to `enabled` for
    this specific render layer, via a layer-level absolute override
    (RenderLayer.createAbsoluteOverride) — the SAME thing Maya's own
    right-click "Create Absolute Override for Visible Layer" does on an
    attribute in the Attribute Editor. Used to turn specific AOVs off
    per render layer (e.g. utility AOVs off in beauty_All).

    CONFIRMED 2026-08-27: an override created inside a Collection
    (Collection.createAbsoluteOverride) reports isFinalized/isApplied as
    True but never actually connects to the target attribute — Arnold's
    AOV .enabled attribute only takes a Render Setup override when it's
    a direct LAYER-level override, matching what the right-click menu
    builds. This function creates it at the layer level to match.

    Idempotent: if the target attribute already has an incoming
    connection from an absOverride node, its value is just updated
    rather than creating a second, competing override.
    """
    updated = []

    for name in aov_names:
        node = f"aiAOV_{name}"
        if not cmds.objExists(node):
            continue
        attr_plug = f"{node}.enabled"

        existing_override = None
        for src in cmds.listConnections(attr_plug, plugs=True, source=True, destination=False) or []:
            src_node = src.split(".")[0]
            if cmds.nodeType(src_node) == "absOverride":
                existing_override = src_node
                break

        try:
            if existing_override:
                cmds.setAttr(f"{existing_override}.attrValue", enabled)
            else:
                override = layer.createAbsoluteOverride(node, "enabled")
                override.setAttrValue(enabled)
            updated.append(node)
        except Exception as e:
            cmds.warning(f'Could not set enabled-override on {node} at layer {layer.name()}: {e}')

    return updated


def build_render_layers(beauty_aov_names, utility_aov_names, build_utility_layer):
    """
    Build/update "beauty_All" (always) and utility_All whenever it
    should exist — either build_utility_layer says to create it now, or
    it's already present from an earlier Apply (so re-Applying, e.g.
    after Clear AOVs recreated the AOV nodes, keeps utility_All's split
    in sync too, not just on first creation). utility_All mirrors
    beauty_All's "objects" collection but with its "lights" collection
    disabled, and gets AOV-enable overrides so beauty_All only renders
    beauty_aov_names (utility AOVs forced off) while utility_All only
    renders utility_aov_names (beauty_aov_names, which already includes
    RGBA when selected, forced off).
    """
    renderSetupModule, selectorModule = _import_render_setup_modules()
    if renderSetupModule is None:
        return

    _configure_render_setup_prefs()
    rs = renderSetupModule.instance()

    # masterLayer: not renderable for batch rendering. Its underlying node
    # is always named "defaultRenderLayer" in every Maya scene, regardless
    # of what the Render Setup API's layer-lookup methods are called —
    # setting this directly is far more reliable than going through the
    # (officially unsupported, frequently-changing) Render Setup API here.
    try:
        cmds.setAttr("defaultRenderLayer.renderable", 0)
        print("masterLayer set to non-renderable for batch rendering.")
    except Exception as e:
        cmds.warning(f"Could not set masterLayer to non-renderable: {e}")

    def _get_or_create(name):
        try:
            layer = rs.getRenderLayer(name)
        except Exception:
            layer = None
        if layer is not None:
            return layer

        layer = rs.createRenderLayer(name)
        if layer.name() != name:
            # Render Setup auto-suffixes ("utility_All1") when something
            # already exists in the scene under that exact name that it
            # doesn't recognize as a real layer — most likely leftover
            # debris from an earlier failed/partial layer delete. Surface
            # this loudly rather than silently building on the wrong name.
            cmds.warning(
                f'Render Setup created "{layer.name()}" instead of "{name}" — something '
                f'already exists in the scene named "{name}" that Render Setup doesn\'t '
                f'recognize as this layer (check the Outliner for a stray "{name}" node, '
                f'possibly left over from an earlier failed delete, and remove it).'
            )
        return layer

    beauty_layer = _get_or_create("beauty_All")
    override_members, missing_overrides, light_members, missing_lights = _build_objects_and_lights_collections(
        beauty_layer, selectorModule, disable_lights=False
    )
    print(f"Render layer 'beauty_All' ready. objects: {override_members}. lights: {light_members}.")

    message = (
        "Render layer beauty_All ready.\n"
        f"  objects (Sets filter): {', '.join(override_members) or '(none found)'}\n"
        f"  lights: {', '.join(light_members) or '(none found)'}\n"
    )
    missing = list(missing_overrides) + list(missing_lights)

    # Process utility_All whenever it should exist: either we're creating
    # it fresh (build_utility_layer, from the checkbox), or it already
    # exists in the scene from an earlier Apply. Gating this whole block
    # on build_utility_layer alone was the bug reported 2026-08-27: after
    # Clear AOVs (which deletes AOVs but leaves render layers in place),
    # utility_All still existed, so build_utility_layer was False on the
    # rebuild and the beauty/utility AOV-enable overrides below never
    # got reapplied — rebuilt AOVs came back with no per-layer split.
    try:
        utility_layer_already_exists = rs.getRenderLayer("utility_All") is not None
    except Exception:
        utility_layer_already_exists = False

    if build_utility_layer or utility_layer_already_exists:
        utility_layer = _get_or_create("utility_All")
        u_override_members, u_missing_overrides, u_light_members, _u_missing_lights = _build_objects_and_lights_collections(
            utility_layer, selectorModule, disable_lights=True
        )
        print(f"Render layer 'utility_All' ready. objects: {u_override_members}. lights collection disabled.")

        # Clean up the old (broken) collection-nested AOV-off overrides from
        # before 2026-08-27's fix — those overrides never actually connected
        # to anything, just leftover clutter now that overrides are created
        # directly on the layer instead.
        for stale_layer, stale_name in ((beauty_layer, "utility_aovs_off"), (utility_layer, "beauty_aovs_off")):
            stale = {c.name(): c for c in stale_layer.getCollections()}.get(stale_name)
            if stale is not None:
                try:
                    cmds.delete(stale.name())
                except Exception as e:
                    cmds.warning(f'Could not remove stale "{stale_name}" collection on {stale_layer.name()}: {e}')

        # beauty_All: turn off utility AOVs. utility_All: turn off beauty + RGBA/lighting AOVs.
        _set_layer_aov_enabled(beauty_layer, utility_aov_names, False)
        _set_layer_aov_enabled(utility_layer, beauty_aov_names, False)

        message += (
            "\nRender layer utility_All ready.\n"
            f"  objects (Sets filter): {', '.join(u_override_members) or '(none found)'}\n"
            "  lights collection: disabled\n"
        )
        for name in u_missing_overrides:
            if name not in missing:
                missing.append(name)

    message += (
        "\nmasterLayer set to non-renderable for batch rendering.\n"
        '"Enable untitled collections" and "Include all lights" turned off.'
    )
    if missing:
        message += f"\n\nNot found in scene (run Scene Setup first?):\n{', '.join(missing)}"

    print(message.replace(chr(10), chr(10) + "  "))


def clear_render_layers():
    """
    Delete the beauty_All / utility_All Render Setup layers entirely
    (with everything nested under them — collections, overrides) so the
    next "Create AOVs + Render Layers" Apply rebuilds them from scratch.
    Testing/reset convenience, added 2026-08-27 while debugging the
    per-layer AOV-enable override not taking effect.

    CORRECTED 2026-08-27: the first version of this function deleted
    each Render Setup layer's underlying compatibility proxy node
    (rs_<name>, a real renderLayer-type node Render Setup auto-creates
    and wires up per layer via that layer's own .legacyRenderLayer
    connection) directly via cmds.delete() — that was wrong. These are
    Render Setup layers, not old-style "legacy render layers"; that
    proxy node exists only for backward-compat interop (things like
    cmds.editRenderLayerGlobals), and Render Setup owns its lifecycle —
    deleting it out from under Render Setup refuses/partially-fails
    (Todd hit this: beauty_All's delete was blocked outright with
    "Render layer is in use", while utility_All's proxy node got
    removed but left the layer's .legacyRenderLayer connection dangling,
    spamming warnings). Fixed to delete the actual Render Setup layer
    through the real API instead: maya.app.renderSetup.model.renderLayer
    .delete(layer) — the documented way to remove one, found by Todd —
    which tears down the proxy node correctly as part of removing the
    layer itself, rather than the other way around.
    """
    renderSetupModule, _ = _import_render_setup_modules()
    if renderSetupModule is None:
        return
    try:
        import maya.app.renderSetup.model.renderLayer as renderLayerModule
    except Exception as e:
        cmds.warning(f"Could not import the renderLayer module: {e}")
        return

    rs = renderSetupModule.instance()
    removed = []
    missing = []
    for name in ("beauty_All", "utility_All"):
        try:
            layer = rs.getRenderLayer(name)
        except Exception:
            layer = None
        if layer is not None:
            try:
                renderLayerModule.delete(layer)
                removed.append(name)
            except Exception as e:
                cmds.warning(f"Could not delete render layer {name}: {e}")
        else:
            missing.append(name)

    print(f"Render layers removed: {removed or '(none)'}. Not found (already clear): {missing or '(none)'}.")


def clear_aovs():
    """
    Delete every AOV this window can create (all BEAUTY/UTILITY_AOVS_ON/OFF
    names + RGBA) from the scene entirely, but leave beauty_All/utility_All
    (and their objects/lights collections) untouched. Testing/reset
    convenience — 2.29.7, replacing the "Clear Render Layers" button:
    Todd confirmed the render layers themselves take real setup work and
    don't need rebuilding every test cycle, only the AOVs do; deleting
    Render Setup layers outright is also still unreliable (see
    clear_render_layers() above, left in place but no longer wired to
    the menu).

    For each aiAOV_<name> node, first deletes any layer-level
    .enabled absOverride nodes targeting it (same lesson as everywhere
    else in this file: clean up what references a node before deleting
    the node, or you leave a dangling connection behind), then removes
    the AOV itself via mtoa's own AOVInterface.removeAOV() — the
    supported way to delete an AOV, rather than raw cmds.delete on the
    node (which wouldn't clean up its EXR driver connections).

    Also removes any leftover AOV-related collections on beauty_All /
    utility_All — specifically "beauty_aovs_off"/"utility_aovs_off", the
    pre-2.29.3 collection-nested-override approach that turned out not
    to work (see aovs_and_render_layers.md project memory) and can still
    be sitting in older scenes as dead weight now that overrides live
    directly on the layer instead — and, as of 2.29.9, each layer's
    system "AOVs" container (AOVCollection), which Render Setup
    auto-creates to hold the layer-level AOV overrides this tool makes.
    """
    try:
        import mtoa.aovs as aovs
    except Exception as e:
        cmds.warning(f"Could not import mtoa.aovs (is Arnold loaded?): {e}")
        return

    _ensure_arnold_render_options()

    interface = aovs.AOVInterface()
    all_names = BEAUTY_AOVS_ON + BEAUTY_AOVS_OFF + UTILITY_AOVS_ON + UTILITY_AOVS_OFF + ["RGBA"]

    removed = []
    missing = []
    for name in all_names:
        node = f"aiAOV_{name}"
        if not cmds.objExists(node):
            missing.append(name)
            continue

        for src in cmds.listConnections(f"{node}.enabled", plugs=True, source=True, destination=False) or []:
            src_node = src.split(".")[0]
            if cmds.nodeType(src_node) == "absOverride":
                try:
                    cmds.delete(src_node)
                except Exception as e:
                    cmds.warning(f"Could not remove override {src_node} on {node}: {e}")

        try:
            interface.removeAOV(name)
            removed.append(name)
        except Exception as e:
            cmds.warning(f"Could not remove AOV {name}: {e}")

    print(f"AOVs removed: {removed or '(none)'}. Not found (already clear): {missing or '(none)'}.")

    stale_collections_removed = []
    for layer_name, collection_name in (("beauty_All", "utility_aovs_off"), ("utility_All", "beauty_aovs_off")):
        layer = _get_render_layer(layer_name)
        if layer is None:
            continue
        stale = {c.name(): c for c in layer.getCollections()}.get(collection_name)
        if stale is not None:
            try:
                cmds.delete(stale.name())
                stale_collections_removed.append(f"{layer_name}/{collection_name}")
            except Exception as e:
                cmds.warning(f'Could not remove stale collection "{collection_name}" on {layer_name}: {e}')

    if stale_collections_removed:
        print(f"Stale AOV-off collections removed: {stale_collections_removed}")

    # Each layer with a layer-level AOV override on it gets its own
    # system "AOVs" container (class AOVCollection, e.g. "AOVCollection" /
    # "AOVCollection1") auto-created by Render Setup to hold that
    # override — visible in the outliner as the "AOVs" row under the
    # layer, Property Editor path "<layer>/AOVCollection/". Confirmed
    # live (2.29.9) via layer.getCollections() that it's a real Collection
    # subclass sitting alongside "objects"/"lights", so it's deleted the
    # same documented way as any other Render Setup collection: the
    # module-level maya.app.renderSetup.model.collection.delete()
    # function, never raw cmds.delete() (same lesson as the render-layer
    # deletion mistake above — let Render Setup's own API own the
    # teardown of its own objects).
    import maya.app.renderSetup.model.collection as collectionModule

    aov_collections_removed = []
    for layer_name in ("beauty_All", "utility_All"):
        layer = _get_render_layer(layer_name)
        if layer is None:
            continue
        for c in layer.getCollections():
            if type(c).__name__ == "AOVCollection":
                try:
                    collection_name = c.name()
                    collectionModule.delete(c)
                    aov_collections_removed.append(f"{layer_name}/{collection_name}")
                except Exception as e:
                    cmds.warning(f'Could not remove AOVCollection "{c.name()}" on {layer_name}: {e}')

    if aov_collections_removed:
        print(f"AOV collections removed: {aov_collections_removed}")


def show_create_aovs_window():
    """
    Combined Create AOVs / Render Layers window. Apply always creates the
    selected AOVs and builds/updates "beauty_All". The "Create Utility
    render layer" checkbox (offered only when utility_All doesn't exist
    yet) additionally builds "utility_All" with the beauty/utility AOV
    split described in build_render_layers(). "Clear AOVs" deletes all
    AOVs (and their per-layer overrides) for a clean retest, leaving the
    render layers themselves in place. "Default" resets every checkbox
    to the hardcoded BEAUTY/UTILITY_AOVS_ON/OFF defaults — mainly useful
    right after Clear AOVs, since the normal seeding logic otherwise
    reflects "does this AOV already exist" (now nothing).
    """
    if cmds.window(CREATE_AOVS_WINDOW, exists=True):
        cmds.deleteUI(CREATE_AOVS_WINDOW)

    beauty_layer_exists = _get_render_layer("beauty_All") is not None
    utility_layer_exists = _get_render_layer("utility_All") is not None
    beauty_state, utility_state, rgba_state = _initial_aov_checkbox_states(beauty_layer_exists)

    window = cmds.window(CREATE_AOVS_WINDOW, title="Create Render Layers / AOVs", sizeable=False, width=300)
    cmds.columnLayout(adjustableColumn=True, columnAlign="left", rowSpacing=6, columnOffset=("both", 12))

    cmds.text(label="")  # top spacer
    cmds.text(label="Create Render Layers / AOVs", font="boldLabelFont", align="left")
    cmds.separator(height=10, style="in")

    cmds.text(label="Beauty AOVs", font="boldLabelFont", align="left")
    beauty_checkboxes = _build_aov_columns(BEAUTY_AOVS_ON, BEAUTY_AOVS_OFF, beauty_state)

    cmds.separator(height=10, style="in")
    cmds.text(label="Utility AOVs", font="boldLabelFont", align="left")
    utility_checkboxes = _build_aov_columns(UTILITY_AOVS_ON, UTILITY_AOVS_OFF, utility_state)

    cmds.text(label="")  # spacer for legibility, between the AOV list and the checkbox below
    utility_layer_checkbox = cmds.checkBox(
        label="Create Utility render layer",
        value=False,
        enable=not utility_layer_exists,
    )

    cmds.separator(height=10, style="in")
    cmds.text(label="Lighting AOVs", font="boldLabelFont", align="left")
    rgba_checkbox = cmds.checkBox(label="RGBA", value=rgba_state)

    cmds.separator(height=10, style="in")

    def on_apply(*_args):
        selected_beauty = [
            name for name, cb in beauty_checkboxes.items() if cmds.checkBox(cb, query=True, value=True)
        ]
        selected_utility = [
            name for name, cb in utility_checkboxes.items() if cmds.checkBox(cb, query=True, value=True)
        ]
        rgba_selected = cmds.checkBox(rgba_checkbox, query=True, value=True)
        build_utility_layer = (
            not utility_layer_exists and cmds.checkBox(utility_layer_checkbox, query=True, value=True)
        )

        cmds.deleteUI(window)

        created, failed = create_aovs(selected_beauty, selected_utility, rgba_selected)
        if failed:
            cmds.warning(f"{len(failed)} AOV(s) failed to create: {[name for name, _ in failed]}")

        beauty_aov_names = list(selected_beauty)
        if rgba_selected:
            beauty_aov_names.append("RGBA")
        build_render_layers(beauty_aov_names, selected_utility, build_utility_layer)

    def on_clear_aovs(*_args):
        confirm = cmds.confirmDialog(
            title="Clear AOVs",
            message="Delete all AOVs (and their per-layer overrides)?\nRender layers are left intact.\nThis cannot be undone.",
            button=["Delete", "Cancel"],
            defaultButton="Cancel",
            cancelButton="Cancel",
            dismissString="Cancel",
        )
        if confirm != "Delete":
            return
        cmds.deleteUI(window)
        clear_aovs()
        show_create_aovs_window()  # reopen fresh, so state/checkboxes reflect the cleared scene

    def on_default(*_args):
        # Reset every checkbox to the hardcoded BEAUTY/UTILITY_AOVS_ON/OFF
        # defaults, regardless of what's currently in the scene. Mainly
        # for after Clear AOVs, where _initial_aov_checkbox_states()
        # otherwise seeds everything unchecked (it reflects "does this
        # AOV already exist", which is now nothing).
        for name, cb in beauty_checkboxes.items():
            cmds.checkBox(cb, edit=True, value=(name in BEAUTY_AOVS_ON))
        for name, cb in utility_checkboxes.items():
            cmds.checkBox(cb, edit=True, value=(name in UTILITY_AOVS_ON))
        cmds.checkBox(rgba_checkbox, edit=True, value=True)

    # 2.32.0: Apply promoted to the big button at the bottom (the primary
    # action here creates AOVs/render layers, not a destructive one), and
    # "Clear AOVs" shortened to "Clear" and moved into its old slot in the
    # top row, alongside Cancel/Default.
    cmds.columnLayout(adjustableColumn=True, columnAlign="center")
    cmds.rowLayout(numberOfColumns=3, columnAttach3=("both", "both", "both"), columnOffset3=(0, 8, 8))
    cmds.button(label="Clear", width=85, command=on_clear_aovs)
    cmds.button(label="Cancel", width=85, command=lambda *a: cmds.deleteUI(window))
    cmds.button(label="Default", width=85, command=on_default)
    cmds.setParent("..")

    cmds.text(label="")  # spacer before the primary action button below
    cmds.button(label="Apply", width=180, command=on_apply)

    cmds.setParent("..")

    cmds.text(label="")  # bottom spacer

    cmds.showWindow(window)


# ------------------------------------------------------------------
# Lighting / Rendering — Update Light Groups
# ------------------------------------------------------------------

ARNOLD_LIGHT_SHAPE_TYPES = ["aiAreaLight", "aiSkyDomeLight", "aiPhotometricLight", "aiLightPortal"]


def update_light_groups():
    """
    Walk every light under each _lights sub-group in the outliner and set
    its AOV Light Group (aiAov) to l_<group name> — e.g. a light under
    _rim gets "l_rim".
    """
    if not cmds.objExists("_lights"):
        cmds.warning('No "_lights" group found. Run Scene Setup first.')
        return

    updated = 0
    skipped = 0

    for group_name in LIGHT_SUBGROUP_NAMES:
        if not cmds.objExists(group_name):
            continue

        light_group_value = f"l_{group_name.lstrip('_')}"

        descendants = cmds.listRelatives(group_name, allDescendents=True, fullPath=True) or []
        light_shapes = set(cmds.ls(descendants, type="light") or [])
        for light_type in ARNOLD_LIGHT_SHAPE_TYPES:
            light_shapes.update(cmds.ls(descendants, type=light_type) or [])

        for light_shape in light_shapes:
            if not cmds.attributeQuery("aiAov", node=light_shape, exists=True):
                skipped += 1
                continue
            try:
                cmds.setAttr(f"{light_shape}.aiAov", light_group_value, type="string")
                updated += 1
            except Exception as e:
                cmds.warning(f"Could not set light group on {light_shape}: {e}")

    print(f"Updated light group name on {updated} light(s) ({skipped} skipped, no aiAov attribute found).")
    cmds.confirmDialog(
        title="Light Groups Updated",
        message=f"Updated {updated} light(s) with their group's light group name.",
        button=["OK"],
    )


# ============================================================
# FILE
# ============================================================

def file_load():
    """
    Open a scene, starting the file browser at the current project's root
    folder (rather than wherever Maya's native Open dialog happens to
    default to). Still checks for unsaved changes first, same as native
    File > Open Scene.
    """
    project_path = get_current_project(warn_if_missing=False)

    kwargs = {
        "fileMode": 1,
        "caption": "Open Scene",
        "fileFilter": "Maya Files (*.ma *.mb);;Maya ASCII (*.ma);;Maya Binary (*.mb);;All Files (*.*)",
    }
    if project_path:
        kwargs["startingDirectory"] = project_path

    result = cmds.fileDialog2(**kwargs)
    if not result:
        return

    file_path = result[0]

    if cmds.file(query=True, modified=True):
        choice = cmds.confirmDialog(
            title="Unsaved Changes",
            message="Save changes before opening a new scene?",
            button=["Save", "Don't Save", "Cancel"],
            defaultButton="Save",
            cancelButton="Cancel",
            dismissString="Cancel",
        )
        if choice == "Cancel":
            return
        if choice == "Save":
            file_save()
            if cmds.file(query=True, modified=True):
                # Still modified means the save was cancelled partway through
                # (e.g. first-time save dialog dismissed) — don't open on top of it.
                return

    try:
        cmds.file(file_path, open=True, force=True)
        align_maya_project()
        print(f"Opened: {file_path}")
    except Exception as e:
        cmds.warning(f"Could not open file: {e}")


def file_save():
    """
    If the scene has already been saved, do a normal save using its
    existing filename/type. If this is the first time saving it, use a
    single native Save-style dialog (navigate + type a name in one
    screen), then confirm the exact versioned filename before committing.
    """
    scene_path = cmds.file(query=True, sceneName=True)

    if scene_path:
        file_type = "mayaBinary" if scene_path.lower().endswith(".mb") else "mayaAscii"
        align_maya_project()
        cmds.file(save=True, type=file_type)
        cmds.file(modified=False)
        print(f"Scene saved: {scene_path}")
        return

    # First-time save: navigate to a location and type a name, both in
    # one native dialog.
    result = cmds.fileDialog2(
        fileMode=0,
        caption="Select Location and Enter File Name",
        okCaption="Save",
    )
    if not result:
        return

    chosen_path = result[0]
    folder_path = os.path.dirname(chosen_path)
    file_name = os.path.basename(chosen_path)

    # Defensive: some Windows Save dialogs append a literal ".*" to the
    # typed name when no explicit extension is given.
    if file_name.endswith(".*"):
        file_name = file_name[:-2]

    # Respect whatever extension the student typed (.ma or .mb); default
    # to .ma if they didn't include one.
    lower_name = file_name.lower()
    if lower_name.endswith(".mb"):
        base_name = file_name[:-3]
        file_ext = ".mb"
    elif lower_name.endswith(".ma"):
        base_name = file_name[:-3]
        file_ext = ".ma"
    else:
        base_name = file_name
        file_ext = ".ma"

    file_type = "mayaBinary" if file_ext == ".mb" else "mayaAscii"
    versioned_name = f"{base_name}.v001{file_ext}"
    file_path = os.path.join(folder_path, versioned_name)

    if os.path.isfile(file_path):
        cmds.warning(f"File already exists: {file_path}")
        return

    # Preview the exact filename (with version + extension) before committing.
    proceed = cmds.confirmDialog(
        title="Confirm Save",
        message=f"This will be saved as:\n{versioned_name}\n\nLocation:\n{folder_path}",
        button=["Save", "Cancel"],
        defaultButton="Save",
        cancelButton="Cancel",
        dismissString="Cancel",
    )
    if proceed != "Save":
        return

    cmds.file(rename=file_path)
    align_maya_project()
    cmds.file(save=True, type=file_type)
    cmds.file(modified=False)

    print(f"Scene saved: {file_path}")
    cmds.confirmDialog(title="Scene Saved", message=f"Saved to:\n{file_path}", button=["OK"])


def file_increment_and_save():
    """Run Maya's built-in Increment and Save (same as File > Increment and Save)."""
    try:
        align_maya_project()
        mel.eval("incrementAndSaveScene 0")
        cmds.file(modified=False)
        print("Scene incremented and saved.")
    except Exception as e:
        cmds.warning(f"Increment and Save failed: {e}")


def prompt_asset_type_choice():
    """Show a Char/Environ/Prop/Custom choice dialog; returns the chosen type string, or None if cancelled."""
    result = cmds.confirmDialog(
        title="Asset Type",
        message="Select the asset type:",
        button=["Char", "Environ", "Prop", "Custom", "Cancel"],
        defaultButton="Char",
        cancelButton="Cancel",
        dismissString="Cancel",
    )
    if result == "Cancel":
        return None
    if result == "Custom":
        return _prompt_for_name("Custom Asset Type", "Asset Type Name:")
    return result.lower()


ASSET_TASK_SUFFIXES = ("model", "rig", "lookdev", "fx")


def guess_asset_name_from_current_scene():
    """
    Strip the version/extension and known task suffix off the currently
    open scene's filename, leaving just the asset name — e.g.
    "sphere_model.v001.ma" -> "sphere".
    """
    scene_path = cmds.file(query=True, sceneName=True)
    if not scene_path:
        return ""

    stem = os.path.splitext(os.path.basename(scene_path))[0]

    version_match = re.match(r"^(.+)\.v\d+$", stem)
    if version_match:
        stem = version_match.group(1)

    for task in ASSET_TASK_SUFFIXES:
        suffix = f"_{task}"
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
            break

    return stem


def find_asset_folder(project_path, asset_name):
    """Search assets/<any type>/<asset_name> for an existing match; return its path or None."""
    assets_dir = os.path.join(project_path, "assets")
    if not os.path.isdir(assets_dir):
        return None

    for type_name in os.listdir(assets_dir):
        type_path = os.path.join(assets_dir, type_name)
        if not os.path.isdir(type_path):
            continue
        candidate = os.path.join(type_path, asset_name)
        if os.path.isdir(candidate):
            return candidate

    return None


def asset_task_maya_dir(asset_dir, task_name):
    """
    Path to a task's Maya WORKSPACE folder (the one containing
    workspace.mel): <asset_dir>/<task_name>/work/maya. Every asset task
    except texture has one (texture is a flat folder with no work/maya
    split) — see build_asset_task_structure. NOT where scene files
    themselves live as of 2.31.4 — see asset_task_scenes_dir below.
    """
    return os.path.join(asset_dir, task_name, "work", "maya")


def asset_task_scenes_dir(asset_dir, task_name):
    """
    Path to where a task's actual .ma/.mb scene files live:
    <asset_dir>/<task_name>/work/maya/scenes.

    2.31.4: Todd — scenes saved through this tool were always landing
    directly in the "maya" workspace folder itself, never in its
    "scenes" subfolder, even though workspace.mel declares "scene" as
    that subfolder (see [[folder_structure]]'s 2.31.0 note, where this
    mismatch was first flagged but deliberately left alone at the time).
    This is now the single source of truth for the actual save/read
    location; asset_task_maya_dir above still means the workspace root.
    """
    return os.path.join(asset_task_maya_dir(asset_dir, task_name), "scenes")


# Which output/<subfolder> a task's Publish copy lands in — see
# publish_scene(). Only tasks that actually publish appear here; fx has no
# publish step, so it's absent and Asset Manager keeps reading its
# work-in-progress files straight from work/maya instead.
PUBLISH_OUTPUT_SUBFOLDER = {
    "model": "geo",
    "lookdev": "geo",
    "rig": "rig",
}


def asset_task_source_dir(asset_dir, task_name):
    """
    Where Asset Manager should look for a task's referenceable files.
    model/rig/lookdev only ever get referenced from their published
    output/<subfolder> (output/geo or output/rig) — that's the whole point
    of Publish, so Asset Manager only ever offers approved versions, not
    work-in-progress. fx has no publish step (yet), so it still reads
    straight from work/maya, same as before the 2.17.0/Publish changes.
    """
    if task_name in PUBLISH_OUTPUT_SUBFOLDER:
        return os.path.join(asset_dir, task_name, "output", PUBLISH_OUTPUT_SUBFOLDER[task_name])
    return asset_task_scenes_dir(asset_dir, task_name)


def list_all_assets(project_path, type_name=None):
    """
    Return sorted (asset_name, asset_dir) pairs for every asset folder under
    assets/<type>/, across every type, regardless of which tasks (if any)
    it has files for. Skips the standalone containers (camera/shader/
    texture) the same way list_assets_with_task does, since those are flat
    folders rather than per-asset containers. Used by Create Custom Folder's
    Asset "All"/specific-asset picker, and by Save As's Type-filtered Asset
    Name dropdown (2.27.0) when type_name is given.

    type_name: if given, only that one asset-category folder (standard or
    custom) is scanned instead of every type.
    """
    assets_dir = os.path.join(project_path, "assets")
    found = []
    if not os.path.isdir(assets_dir):
        return found

    type_names = [type_name] if type_name is not None else os.listdir(assets_dir)
    for candidate_type in type_names:
        if candidate_type in ASSET_STANDALONE_TYPES:
            continue
        type_path = os.path.join(assets_dir, candidate_type)
        if not os.path.isdir(type_path):
            continue
        for asset_name in os.listdir(type_path):
            asset_path = os.path.join(type_path, asset_name)
            if os.path.isdir(asset_path):
                found.append((asset_name, asset_path))

    return sorted(found, key=lambda pair: pair[0])


def list_asset_category_types(project_path):
    """
    Return sorted names of every asset-category folder that actually exists
    under assets/ — the standard types (char/environ/prop) plus any custom
    types Todd has created (via Create Asset Folders' or Create New Asset's
    "Custom" option) — excluding the standalone containers (camera/shader/
    texture), which aren't per-asset categories. Added 2.27.0 so Save As
    and Asset Manager's Add Asset window can offer a real "Type" picker
    instead of silently skipping type for custom-type assets.
    """
    assets_dir = os.path.join(project_path, "assets")
    if not os.path.isdir(assets_dir):
        return []
    return sorted(
        name for name in os.listdir(assets_dir)
        if name not in ASSET_STANDALONE_TYPES and os.path.isdir(os.path.join(assets_dir, name))
    )


# ------------------------------------------------------------------
# Asset Manager — Reference Rig / Shade Asset
# ------------------------------------------------------------------

ASSET_PICKER_WINDOW = "assetPickerWindow"
VERSIONED_FILE_PATTERN = re.compile(r"^(.+)\.v(\d+)\.(ma|mb)$", re.IGNORECASE)


def namespace_for_versioned_file(filename):
    """
    Build the namespace to reference/swap a versioned file under, e.g.
    "harbor_env_model.v014.ma" -> "harbor_env_model_v014". Namespaces
    can't contain dots, so this is the same "underscore the version"
    naming Maya's own default referencing would produce — computed
    explicitly here so it stays consistent between the initial reference
    and any later version swap (Maya doesn't auto-update a reference's
    namespace when you point it at a different file).
    """
    return os.path.splitext(filename)[0].replace(".", "_")


def _unique_reference_namespace(base_namespace):
    """
    2.24.1 — the Asset Manager panel's "+" can now stage the same asset
    more than once before Update (Todd: "this allows the user to add as
    many as they want to the scene"), so two staged adds can end up with
    the same base namespace (same asset + version referenced twice).
    Maya reference namespaces must be unique, so this appends _2, _3,
    ... until it finds one that isn't already taken — checked live
    against the actual scene (cmds.namespace(exists=...)), so it also
    naturally steers clear of anything already referenced outside this
    panel, not just other instances added in the same Update batch.
    """
    if not cmds.namespace(exists=base_namespace):
        return base_namespace
    n = 2
    while cmds.namespace(exists=f"{base_namespace}_{n}"):
        n += 1
    return f"{base_namespace}_{n}"


def list_assets_with_task(project_path, task_name, type_name=None):
    """
    Return sorted names of every asset (across all types, or just one when
    type_name is given — 2.27.0, for Asset Manager's Add Asset Type filter)
    that has at least one versioned file for task_name — read from
    asset_task_source_dir, so model/rig/lookdev only count PUBLISHED
    versions (output/geo or output/rig), while fx still counts
    work-in-progress files (work/maya).
    """
    assets_dir = os.path.join(project_path, "assets")
    found = []
    if not os.path.isdir(assets_dir):
        return found

    candidate_types = [type_name] if type_name is not None else os.listdir(assets_dir)
    for candidate_type in candidate_types:
        if candidate_type in ASSET_STANDALONE_TYPES:
            continue
        type_path = os.path.join(assets_dir, candidate_type)
        if not os.path.isdir(type_path):
            continue
        for asset_name in os.listdir(type_path):
            source_dir = asset_task_source_dir(os.path.join(type_path, asset_name), task_name)
            if not os.path.isdir(source_dir):
                continue
            stub = f"{asset_name}_{task_name}"
            if any(
                VERSIONED_FILE_PATTERN.match(f) and f.startswith(stub + ".v")
                for f in os.listdir(source_dir)
            ):
                found.append(asset_name)

    return sorted(set(found))


def get_asset_task_versions(project_path, asset_name, task_name, type_name=None):
    """
    Return every versioned filename for asset_name's task_name files, newest
    version first — read from asset_task_source_dir (published output for
    model/rig/lookdev, work-in-progress work/maya for fx).

    type_name: if given (2.27.0), resolves directly to assets/<type_name>/
    <asset_name> instead of find_asset_folder's scan-every-type lookup —
    avoids ambiguity if two different types ever have same-named assets.
    """
    if type_name is not None:
        candidate = os.path.join(project_path, "assets", type_name, asset_name)
        asset_dir = candidate if os.path.isdir(candidate) else None
    else:
        asset_dir = find_asset_folder(project_path, asset_name)
    if not asset_dir:
        return []
    task_maya_dir = asset_task_source_dir(asset_dir, task_name)
    if not os.path.isdir(task_maya_dir):
        return []

    stub = f"{asset_name}_{task_name}"
    versions = []
    for name in os.listdir(task_maya_dir):
        match = VERSIONED_FILE_PATTERN.match(name)
        if match and match.group(1) == stub:
            versions.append((int(match.group(2)), name))

    versions.sort(key=lambda pair: pair[0], reverse=True)
    return [name for _version, name in versions]


def show_asset_reference_picker(task_name, window_title, on_close=None):
    """
    Shared window for Reference Rig Asset / Reference Shade Asset (and for
    Asset Manager's "+ Add Asset"): pick an asset (left) and a version of
    its task_name file (right), then reference it into the scene.

    If on_close is given, it's called once the window goes away, however
    that happens (Add Asset, Close, or the empty-state Close) — used by
    Asset Manager to reopen itself with the freshly added reference.
    """
    project_path = get_current_project()
    if not project_path:
        return

    assets_with_task = list_assets_with_task(project_path, task_name)

    if cmds.window(ASSET_PICKER_WINDOW, exists=True):
        cmds.deleteUI(ASSET_PICKER_WINDOW)

    window = cmds.window(ASSET_PICKER_WINDOW, title=window_title, sizeable=False, width=360)
    cmds.columnLayout(adjustableColumn=True, columnAlign="left", rowSpacing=6, columnOffset=("both", 12))

    cmds.text(label="")  # top spacer
    cmds.text(label=window_title, font="boldLabelFont", align="left")
    cmds.separator(height=10, style="in")

    if not assets_with_task:
        cmds.text(label=f"No assets with {task_name} files found.", align="left")
        cmds.separator(height=10, style="in")

        def on_empty_close(*_args):
            cmds.deleteUI(window)
            if on_close:
                on_close()

        cmds.columnLayout(adjustableColumn=True, columnAlign="center")
        cmds.button(label="Close", width=70, command=on_empty_close)
        cmds.setParent("..")
        cmds.text(label="")
        cmds.showWindow(window)
        return

    cmds.rowLayout(numberOfColumns=2, columnWidth2=(160, 160), adjustableColumn2=2)
    asset_dropdown = cmds.optionMenu()
    for asset_name in assets_with_task:
        cmds.menuItem(label=asset_name, parent=asset_dropdown)
    version_dropdown = cmds.optionMenu()
    cmds.setParent("..")

    version_lookup = {}  # version label (e.g. "v003") -> actual filename

    def refresh_versions(*_args):
        for item in cmds.optionMenu(version_dropdown, query=True, itemListLong=True) or []:
            cmds.deleteUI(item)
        version_lookup.clear()

        asset_name = cmds.optionMenu(asset_dropdown, query=True, value=True)
        for filename in get_asset_task_versions(project_path, asset_name, task_name):
            match = VERSIONED_FILE_PATTERN.match(filename)
            version_label = f"v{match.group(2)}" if match else filename
            version_lookup[version_label] = filename
            cmds.menuItem(label=version_label, parent=version_dropdown)

    cmds.optionMenu(asset_dropdown, edit=True, changeCommand=refresh_versions)
    refresh_versions()

    cmds.separator(height=10, style="in")

    def do_reference():
        asset_name = cmds.optionMenu(asset_dropdown, query=True, value=True)
        version_label = cmds.optionMenu(version_dropdown, query=True, value=True)
        filename = version_lookup.get(version_label)
        if not filename:
            cmds.warning("Could not resolve the selected version.")
            return

        asset_dir = find_asset_folder(project_path, asset_name)
        if not asset_dir:
            cmds.warning(f"Could not find asset folder for {asset_name}.")
            return

        file_path = os.path.join(asset_task_source_dir(asset_dir, task_name), filename)
        try:
            # Explicit namespace matching the full versioned filename,
            # e.g. "harbor_env_model_v014" — see namespace_for_versioned_file.
            cmds.file(file_path, reference=True, namespace=namespace_for_versioned_file(filename))
            print(f"Referenced: {file_path}")
        except Exception as e:
            cmds.warning(f"Could not reference {file_path}: {e}")

    def on_add_asset(*_args):
        do_reference()
        cmds.deleteUI(window)
        if on_close:
            on_close()

    def on_add_and_keep_open(*_args):
        do_reference()

    def on_close_button(*_args):
        cmds.deleteUI(window)
        if on_close:
            on_close()

    # "both"-attach columns were letting a button's actual rendered size
    # (e.g. "Add and Keep Open" needing more than its nominal width)
    # throw off the row's total width, which then threw off the centering
    # column wrapping it. Plain "left"-attach columns with fixed widths
    # give the wrapper an accurate total width to center against.
    cmds.columnLayout(adjustableColumn=True, columnAlign="center")
    cmds.rowLayout(
        numberOfColumns=3,
        columnAttach3=("left", "left", "left"),
        columnOffset3=(0, 10, 10),
    )
    cmds.button(label="Add Asset", width=90, command=on_add_asset)
    cmds.button(label="Add and Keep Open", width=150, command=on_add_and_keep_open)
    cmds.button(label="Close", width=70, command=on_close_button)
    cmds.setParent("..")
    cmds.setParent("..")

    cmds.text(label="")  # bottom spacer

    cmds.showWindow(window)


def show_reference_rig_asset_window():
    show_asset_reference_picker("rig", "Asset Rig Picker")


def show_reference_shade_asset_window():
    show_asset_reference_picker("lookdev", "Asset Shade Picker")


# ------------------------------------------------------------------
# Asset Manager — Scene References Table
# ------------------------------------------------------------------
#
# Design reference: asset_manager_design.jpg. That mockup is a Qt-style
# dark card UI; this is built with native cmds windows (like every other
# window in this file), so it approximates the layout rather than
# matching it pixel-for-pixel. Each row is: checkbox, type, asset name,
# version dropdown, remove ("X").
#
# The checkbox and the "X" are independent: the checkbox marks rows for
# "Update All" (bump to the newest version); "X" darkens to mark a row
# for removal. The version dropdown reads red whenever it isn't sitting
# on the newest available version. Nothing changes in the scene until
# Commit is pressed — Close discards every staged change.

ASSET_MANAGER_WINDOW = "assetManagerWindow"
ASSET_MANAGER_ADD_WINDOW = "assetManagerAddWindow"

# Display label + sort order for each task. Tasks not listed here still
# show up, sorted last under their raw task name.
ASSET_MANAGER_TASK_LABELS = {
    "model": "Model",
    "rig": "Rig",
    "lookdev": "Shade",
    "fx": "FX",
    "texture": "Texture",
    "cache": "Cache",
}
ASSET_MANAGER_TASK_ORDER = ("model", "rig", "lookdev", "fx", "texture", "cache")

# Add Asset's Type dropdown only offers what's actually referenceable —
# model/rig/lookdev/fx (same set as ASSET_TASK_SUFFIXES; texture is a flat
# folder, never referenced) — plus the synthetic "Cache" entry below, which
# isn't a per-asset task at all: it pulls from shots/<shot>/anim/output/cache
# instead of an asset folder. ASSET_MANAGER_CACHE_TASK is a sentinel value
# (never a real ASSET_TASKS/ASSET_TASK_SUFFIXES member) used internally by
# show_asset_manager_add_window to branch its Add Asset logic.
ASSET_MANAGER_CACHE_TASK = "cache"
ASSET_MANAGER_CACHE_LABEL = "Cache"

# Cache files live at shots/<shot>/anim/output/cache/<objectName>_anim.vNNN.abc
# — one independently-versioned family per exported object (see
# export_selection_to_cache), same versioned-filename convention as
# everything else, just .abc instead of .ma/.mb.
CACHE_VERSIONED_FILE_PATTERN = re.compile(r"^(.+)\.v(\d+)\.(abc)$", re.IGNORECASE)


def get_shot_cache_dir(project_path, shot_name):
    """Path to a shot's anim cache output folder: shots/<shot>/anim/output/cache."""
    return os.path.join(project_path, "shots", shot_name, "anim", "output", "cache")


def get_next_cache_version(folder_path, filename_stub):
    """Scan folder_path for <filename_stub>.vNNN.abc files and return the next version number (1 if none exist yet)."""
    highest = 0
    if os.path.isdir(folder_path):
        pattern = re.compile(rf"^{re.escape(filename_stub)}\.v(\d+)\.(abc)$", re.IGNORECASE)
        for name in os.listdir(folder_path):
            match = pattern.match(name)
            if match:
                highest = max(highest, int(match.group(1)))
    return highest + 1


def get_shot_cache_names(project_path, shot_name):
    """
    Return the distinct cache name stubs found in a shot's anim cache
    folder (e.g. ["camera_anim", "georgeMichael_anim", "hat_anim"],
    sorted) — one per object that's ever been cached for this shot, since
    Export Cache writes one independently-versioned file per top-level
    selected object rather than one combined file per shot.
    """
    cache_dir = get_shot_cache_dir(project_path, shot_name)
    if not os.path.isdir(cache_dir):
        return []

    stubs = set()
    for name in os.listdir(cache_dir):
        match = CACHE_VERSIONED_FILE_PATTERN.match(name)
        if match:
            stubs.add(match.group(1))
    return sorted(stubs)


def get_shot_cache_versions(project_path, shot_name, cache_name):
    """Return every versioned .abc filename for one cache name stub in a shot's anim cache folder, newest first."""
    cache_dir = get_shot_cache_dir(project_path, shot_name)
    if not os.path.isdir(cache_dir):
        return []

    pattern = re.compile(rf"^{re.escape(cache_name)}\.v(\d+)\.(abc)$", re.IGNORECASE)
    versions = []
    for name in os.listdir(cache_dir):
        match = pattern.match(name)
        if match:
            versions.append((int(match.group(1)), name))

    versions.sort(key=lambda pair: pair[0], reverse=True)
    return [name for _version, name in versions]


# --- Cache attachment tracking (2.22.0) ---------------------------------
# AbcImport -connect merges cache data straight onto existing nodes (see
# the 2.21.3 fix) — it doesn't create a reference or a namespace, so there
# was nothing for Asset Manager to find and list once a cache was
# attached. These two custom string attrs, stamped onto the merged-onto
# node (obj_node) the moment a cache is attached, are what let Asset
# Manager rediscover "this node has a cache merged onto it" later and
# show it as its own row — see _asset_manager_collect_cache_rows below.
CACHE_ATTR_SHOT = "cacheShot"
CACHE_ATTR_NAME = "cacheName"
# 2.24.8: which versioned cache FILENAME is actually attached right now,
# stamped explicitly at tag time. Needed once _attach_cache_to_node
# started importing from a throwaway scratch copy instead of the real
# cache file (see that function's 2.24.8 note) — the connected
# AlembicNode's own .abc_File attribute now points at the scratch path,
# not a real "<name>.vNNN.abc" file, so it can no longer be parsed for
# the currently-attached version. This attribute is the source of truth
# instead; _asset_manager_collect_cache_rows falls back to the old
# .abc_File-parsing behavior only for nodes tagged before this existed.
CACHE_ATTR_FILE = "cacheFile"


def _find_connected_alembic_nodes(obj_node):
    """Every AlembicNode currently driving obj_node or any of its descendants."""
    descendants = cmds.listRelatives(obj_node, allDescendents=True, fullPath=True) or []
    nodes = set()
    for node in [obj_node] + descendants:
        nodes.update(cmds.listConnections(node, type="AlembicNode", source=True, destination=False) or [])
    return list(nodes)


_NAMESPACE_ASSET_TASK_PATTERN = re.compile(
    rf"^(.+)_({'|'.join(re.escape(t) for t in ASSET_TASK_SUFFIXES)})_v\d+(?:_\d+)?$", re.IGNORECASE
)


def _asset_task_from_namespace(namespace):
    """
    Best-effort (asset_name, task_name) pull from a reference namespace
    built by namespace_for_versioned_file/_unique_reference_namespace,
    e.g. "georgeMichael_lookdev_v002_2" -> ("georgeMichael", "lookdev").
    Returns (None, None) if namespace doesn't match that convention.
    """
    match = _NAMESPACE_ASSET_TASK_PATTERN.match(namespace or "")
    if not match:
        return None, None
    return match.group(1), match.group(2).lower()


def _ensure_obj_node_grouped(obj_node, asset_name=None, task_name=None):
    """
    2.24.15: see the 2.24.15 note on _attach_cache_to_node for the full
    story — Todd's native-Maya (no scripting) repro showed AbcImport's
    -connect fails to wire once more than one candidate target sits at
    the DAG root, and parenting each target under its own group node
    fixed it. If obj_node currently has no parent (i.e. is a root-level
    node), wraps it in a freshly created group. Idempotent — a no-op if
    obj_node is already parented, so this is safe to call every time
    _attach_cache_to_node runs, not just the first.

    2.24.16: Todd — group name simplified to "<asset>_<task>_<number>"
    (was a sanitized dump of the node's full namespaced path). Callers
    that already know asset_name/task_name (every real cache-attach call
    site does) pass them straight through; otherwise this falls back to
    parsing them out of obj_node's own namespace via
    _asset_task_from_namespace, and only as a last resort — namespace
    didn't match the expected "<asset>_<task>_vNNN" convention at all —
    falls back to the old sanitized-path naming so grouping still works
    (just without a clean name) rather than silently skipping it. The
    trailing "#" is Maya's own auto-increment-for-uniqueness syntax, which
    is what actually produces the "_<number>" suffix Todd asked for.
    Also called now (2.24.16) from the general Add Asset flow for
    Shade/lookdev assets, not just the cache-attach path, per Todd: "the
    same for a shade asset import on its own" — see do_add() in
    show_asset_manager_add_window.

    2.31.8 BUG FIX: now returns the node's current long-path name — None
    if obj_node couldn't be uniquely resolved at all. Grouping a
    previously-root-level node changes its full DAG path (it now sits
    one level deeper, under the new group), so any caller that goes on
    to use the ORIGINAL obj_node string afterward is working with a
    stale path. That's exactly what broke Asset Manager's cache-version
    rollback: Todd — "on first run, anim caches wouldnt roll back to an
    older version in asset manager.. but run a second time it worked,"
    later pinned down with an actual error, 'Could not uniquely resolve
    "|box_anim_default_3:rigRoot" to attach the cache onto (0 match(es)
    found)' — that's this exact staleness, one call after the node got
    grouped for the first time in the session.

    2.31.9 BUG FIX: 2.31.8's own re-resolve after grouping still used
    `node` — the PRE-grouping full path — to re-query the post-grouping
    path (`cmds.ls(node, long=True)`). That's the identical mistake one
    line later: a Maya pipe-separated full-path string is matched as an
    exact hierarchy, so the old path doesn't resolve to anything once
    the node has a new parent either, and Todd hit the exact same "0
    match(es) found" error on retest (now against
    "box_anim_default_2:rigRoot"). Switched to the node's UUID (stable
    across reparenting/renaming, unlike any name-based path), captured
    right before grouping.

    2.31.10 BUG FIX: the 2.31.9 attempt passed the UUID as `ls(uuid=...)`
    for the REVERSE lookup too — wrong API usage. `uuid` is a boolean
    flag: `cmds.ls(node, uuid=True)` returns node's UUID (this half was
    right), but querying BY a UUID isn't `cmds.ls(uuid=<value>)` at all —
    Maya's `ls` only accepts `uuid` as True/False, and raised exactly
    that: "Flag 'uuid' must be passed a boolean argument." To look a
    node up by its UUID, pass the UUID STRING itself as the object name
    argument — `cmds.ls(<uuid-string>, long=True)` — Maya auto-detects a
    UUID-formatted string there. Fixed accordingly below.
    """
    resolved = cmds.ls(obj_node, long=True) or []
    if len(resolved) != 1:
        return None
    node = resolved[0]
    if cmds.listRelatives(node, parent=True, fullPath=True):
        return node

    if not asset_name or not task_name:
        short_name = node.strip("|").split("|")[-1]
        namespace = short_name.split(":")[-2] if ":" in short_name else None
        parsed_asset, parsed_task = _asset_task_from_namespace(namespace)
        asset_name = asset_name or parsed_asset
        task_name = task_name or parsed_task

    if asset_name and task_name:
        group_base = f"{asset_name}_{task_name}"
    else:
        group_base = node.strip("|").replace(":", "_").replace("|", "_")

    node_uuids = cmds.ls(node, uuid=True) or []
    cmds.group(node, name=f"{group_base}_#")

    if node_uuids:
        resolved_after = cmds.ls(node_uuids[0], long=True) or []
        if len(resolved_after) == 1:
            return resolved_after[0]
    # Fallback (UUID lookup unavailable/ambiguous for some reason): the
    # node's short namespaced name is still globally unique even though
    # its full path changed, so a non-full-path ls still finds it.
    fallback = cmds.ls(node.split("|")[-1], long=True) or []
    return fallback[0] if len(fallback) == 1 else None


def _attach_cache_to_node(cache_file_path, obj_node, asset_name=None, task_name="lookdev"):
    """
    Merge cache_file_path onto obj_node via AbcImport -connect — the real
    "Import Under Current Selection > Merge" behavior (see the 2.21.3
    fix). Any AlembicNode(s) already driving obj_node are deleted first,
    so re-running this to swap to a newer cache version (Asset Manager's
    cache row Version dropdown) replaces the old cache data instead of
    stacking a second AlembicNode on top of it.

    2.24.6: Todd — "if the user brings in multiples of the same cache..
    it doesnt attach to a shade file properly.. the first time it comes
    in, it attaches and works.. after that.. the shade file loads with
    no anim cache applied even though it says it does." Two hardening
    changes were made, since a live Maya session wasn't available to pin
    down AbcImport's exact internal cause:

    1. obj_node was resolved to its unique LONG (full DAG path) name
       before doing anything, on the theory that the short
       `f"{namespace}:OBJ"` form every caller builds could be ambiguous
       once the SAME Shade asset is referenced more than once. **Reverted
       in 2.24.7** — see below, this is what actually broke attach again.
    2. The attach is VERIFIED after AbcImport runs — if no AlembicNode
       ends up connected to obj_node afterward, this raises instead of
       returning normally, so every caller's existing try/except (the
       default-shader fallback in AssetManagerPanel._commit_cache_add,
       the error list in _do_update's version-swap branch, etc.) treats
       it as a real failure instead of a false success. Kept in 2.24.7 —
       this part was sound and is exactly what surfaced the regression
       below as a "falls back to default shader" report instead of a
       silent no-op.

    2.24.7: Todd reported caches not attaching again, AND now falling
    back to the default shader where they used to attach. Re-reading
    2.24.6's own reasoning: `_unique_reference_namespace` already
    guarantees every reference namespace is globally unique, so
    "<namespace>:OBJ" was never actually ambiguous in the first place —
    a namespace can only ever contain one node named "OBJ" (Setup
    Scene's own convention). The 2.24.6 "fix" for a problem that didn't
    exist had a real side effect: it swapped what gets passed to
    `cmds.select()`/`cmds.AbcImport(connect=...)` from the short
    namespace-qualified form (confirmed working with Todd in Maya,
    2.21.3) to the resolved long DAG-path form (`"|group|ns:OBJ"`,
    never confirmed). That reversion is kept below, but a follow-up
    screenshot from Todd showed it wasn't the actual cause.

    2.24.8: Todd's screenshot pinned this down precisely — bringing the
    SAME cache in 3 times in one Maya session attached correctly exactly
    once; the 2nd and 3rd times fell back to the default shader every
    time, each onto its OWN freshly-referenced, uniquely-namespaced
    Shade asset instance (so per-instance node-name ambiguity, 2.24.6's
    theory, is ruled out — each attempt's obj_node was already distinct
    and unambiguous). The one thing genuinely identical across all 3
    attempts is the cache_file_path being handed to AbcImport. Maya's
    Alembic plugin is known to cache/reuse archive readers keyed by file
    path internally; re-importing the exact same path a second time in
    one session doesn't reliably behave the same as the first — a
    documented category of AbcImport quirk, not something exposed via
    any cmds.AbcImport flag to work around directly. Workaround: copy
    cache_file_path to a throwaway, uniquely-named file right beside it
    (in a hidden `.attach_tmp` folder) before every single attach, and
    import THAT instead — Maya/Alembic then never sees the same path
    twice no matter how many times the same logical cache gets attached
    in one session. The scratch copy is left on disk rather than deleted
    right after import, since the resulting AlembicNode may stream from
    it lazily rather than fully loading up front (deleting it
    immediately risked breaking playback/scrubbing later). Since the
    AlembicNode's own `.abc_File` now points at a scratch path instead of
    the real versioned cache file, `_asset_manager_collect_cache_rows`
    no longer reads the current version from `.abc_File` — see
    CACHE_ATTR_FILE below, stamped explicitly at tag time instead.

    UNCONFIRMED — this is a workaround for a suspected Maya/Alembic
    plugin behavior, not a fully diagnosed root cause (no live Maya
    session was available to confirm the caching theory directly). If
    caches still don't attach past the first time after this, that
    theory was wrong and this needs a different approach — worth telling
    me exactly what's now happening (still falls back? errors outright?)
    rather than just "still broken," since the specific failure mode is
    what narrows this down each round.

    2.24.13: Todd's 2.24.12 test (cleanup off) delivered exactly the
    evidence 2.24.10's diagnostic was built for. Outliner showed genuinely
    distinct namespaces (`georgeMichael_lookdev_v002` then `..._v002_2`)
    — NOT namespace/name reuse, ruling out every theory from 2.24.6
    through 2.24.9 for good. The warning itself resolved the (a)/(b) split
    from the 2.24.10 comment above: "an AlembicNode WAS created
    (aedd492c...AlembicNode) but never got wired onto
    "georgeMichael_lookdev_v002_2:OBJ" — a -connect wiring problem
    specifically." Case (a), confirmed: AbcImport reads the archive and
    creates the node fine, every single time — it's specifically the
    -connect hookup that stops wiring after the first successful call in
    a session, regardless of target/source identity (both were already
    unique here).

    2.24.13 tried force-unloading/reloading the AbcImport plugin
    immediately before each connect-mode call, on the theory that the
    plugin keeps internal connect-mode state that doesn't reset between
    calls. **REVERTED in 2.24.14 — Maya crashed on Todd's very next test.**
    Force-unloading a plugin while node types it registers (AlembicNode)
    are still live in the scene — which they always are here, since the
    whole point is a REPEAT attach with an existing AlembicNode already
    connected from the first successful attempt — is unsafe and a
    plausible/likely crash cause. Do not retry plugin unload/reload as an
    approach for this bug. The (a)-confirmed diagnosis above (AlembicNode
    creation always succeeds; only the -connect wiring itself stops
    working after the first call in a session) still stands and is the
    best lead so far — just don't reach for unloading the plugin to
    address it.

    2.24.15: Todd found the real trigger, via a native-Maya repro test
    (File > Cache > Import Alembic, no scripting at all) — the SAME
    "-connect wiring problem" reproduces with zero pipeline code involved
    whenever the target OBJ node sits at the DAG root (top level, no
    parent). Referencing/importing a second Shade asset leaves its OBJ
    node parentless too, identically to the first one, differing only by
    namespace — and that's exactly what breaks -connect. When Todd instead
    did File > Import (which auto-creates a wrapper "group"/"group1" node
    for each import) so each OBJ ended up parented under its own group,
    -connect wired correctly onto both, every time. So this was never
    about node identity/naming/plugin state at all — it's specifically
    that AbcImport's -connect matcher doesn't reliably resolve which
    *root-level* node it's being pointed at once more than one is present,
    even though each is individually addressable and unambiguous by its
    full namespace-qualified name. Fix: `_ensure_obj_node_grouped` below —
    called here before the AbcImport call — wraps obj_node in a fresh,
    uniquely-named group the first time it's ever attached to (a no-op,
    idempotent check, on every call after that), so no OBJ node this
    function ever targets is left sitting at DAG root. Grouping a node
    does not move it (the new group has an identity transform), so this
    has no visible effect beyond adding one Outliner level.
    """
    # 2.31.8: use the path _ensure_obj_node_grouped hands back, not the
    # one obj_node came in as — grouping a root-level node changes its
    # full DAG path, and re-resolving via the OLD obj_node string right
    # after is exactly what produced the "0 match(es) found" bug on a
    # cache's first version-swap of a session (see that function's
    # 2.31.8 note for the full story).
    grouped_obj_node = _ensure_obj_node_grouped(obj_node, asset_name=asset_name, task_name=task_name)
    if grouped_obj_node:
        obj_node = grouped_obj_node
    resolved = cmds.ls(obj_node, long=True) or []
    if len(resolved) != 1:
        raise RuntimeError(
            f'Could not uniquely resolve "{obj_node}" to attach the cache onto '
            f"({len(resolved)} match(es) found)."
        )

    scratch_dir = os.path.join(os.path.dirname(cache_file_path), ".attach_tmp")
    os.makedirs(scratch_dir, exist_ok=True)
    scratch_path = os.path.join(scratch_dir, f"{uuid.uuid4().hex}_{os.path.basename(cache_file_path)}")
    shutil.copy2(cache_file_path, scratch_path)

    for old_node in _find_connected_alembic_nodes(obj_node):
        try:
            cmds.delete(old_node)
        except Exception:
            pass

    # 2.24.10: diagnostic only, no behavior change — 2.24.7/2.24.8/2.24.9
    # each targeted a different theory for why a 2nd/3rd connect= call in
    # one session fails (node-name ambiguity, same-file-path plugin
    # caching, bare-named nodes colliding), and Todd's logs disproved
    # every one of them in turn: the failure happens identically even
    # with a uniquely-named scratch file (rules out path caching) and
    # even when nothing else in the scene shares a name with the cache's
    # own hierarchy (rules out name collision, assuming 2.24.9's
    # namespaced-fallback fix was actually exercised on a clean scene).
    # This narrows it to something at the AbcImport-plugin-call level
    # itself rather than anything about the target/source identity — but
    # there are two distinct ways that could look: (a) AbcImport reads
    # the archive and creates an AlembicNode, but fails to WIRE it onto
    # obj_node (a -connect-specific problem), or (b) AbcImport silently
    # does nothing at all past the first call in a session (a broader
    # plugin-state problem, connect= incidental). Recording whether ANY
    # new AlembicNode showed up anywhere in the scene — not just
    # connected to obj_node — distinguishes the two the next time this
    # raises, without needing another guess-and-ship round first.
    before_alembic_nodes = set(cmds.ls(type="AlembicNode") or [])
    # 2.24.11: Todd's own read of the flow ("select the next target,
    # merge, deselect, select the next one, merge again") pointed at one
    # real gap versus what the code actually did — `cmds.select(obj_node,
    # replace=True)` produces the same end selection as a clear-then-
    # select, but isn't literally that; and there was no forced refresh
    # between selecting and calling AbcImport, so it's at least possible
    # the plugin reads selection at a point where Maya hasn't fully
    # processed the change yet in a fast back-to-back scripted loop (as
    # opposed to interactive use, where a UI event cycle happens between
    # clicks). Cheap, safe, purely additive — explicit clear before
    # select, plus a forced cmds.refresh() before the AbcImport call.
    cmds.select(clear=True)
    cmds.select(obj_node, replace=True)
    cmds.refresh(force=True)
    cmds.AbcImport(scratch_path, mode="import", connect=obj_node)
    after_alembic_nodes = set(cmds.ls(type="AlembicNode") or [])
    new_alembic_nodes = after_alembic_nodes - before_alembic_nodes

    if not _find_connected_alembic_nodes(obj_node):
        if new_alembic_nodes:
            detail = (
                f"an AlembicNode WAS created ({', '.join(sorted(new_alembic_nodes))}) but never got wired "
                f'onto "{obj_node}" — a -connect wiring problem specifically.'
            )
        else:
            detail = (
                "no AlembicNode was created at all (not even an orphaned/unconnected one) — "
                "AbcImport itself didn't do anything this call, not just the -connect wiring."
            )
        raise RuntimeError(
            f'AbcImport reported no error, but no AlembicNode ended up connected to "{obj_node}" — '
            f"the cache did not actually attach. Diagnostic: {detail}"
        )

    # 2.31.12 BUG FIX: return the RESOLVED obj_node (post-grouping, if
    # grouping happened) so callers that tag/track this node afterward
    # (_tag_cache_attachment, and AssetManagerPanel._do_update's own
    # item["cache_obj_node"] bookkeeping) use the same live path this
    # function actually attached onto — not the stale pre-grouping one
    # they originally called this with. This was the actual remaining
    # cause of the "No object matches name" traceback: the attach/swap
    # itself was working correctly by 2.31.10, but _do_update's very
    # next line, `_tag_cache_attachment(item["cache_obj_node"], ...)`,
    # was still passing the ORIGINAL stale obj_node string (this
    # function never handed the resolved one back out), and
    # _tag_cache_attachment's cmds.attributeQuery raises (unlike
    # cmds.ls, which just returns empty) on a name that no longer
    # resolves — hence the traceback landing there instead of here.
    return obj_node


def _tag_cache_attachment(obj_node, shot_name, cache_name, filename=None):
    """
    Stamp obj_node with which shot/cache-name a cache was merged onto it
    from, so Asset Manager can find it again. 2.24.8: also stamps
    CACHE_ATTR_FILE with the real versioned cache filename when given
    (e.g. "georgeMichael_anim.v002.abc") — see that constant's comment
    for why this is now the source of truth for "what version is
    currently attached" instead of parsing the connected AlembicNode's
    .abc_File. `filename` is optional (kept so any existing call that
    genuinely has no filename handy — there are none left, but this
    keeps the signature forgiving — doesn't have to change) but every
    call site in this file passes it as of 2.24.8.
    """
    tags = {CACHE_ATTR_SHOT: shot_name, CACHE_ATTR_NAME: cache_name}
    if filename:
        tags[CACHE_ATTR_FILE] = filename
    for attr, value in tags.items():
        if not cmds.attributeQuery(attr, node=obj_node, exists=True):
            cmds.addAttr(obj_node, longName=attr, dataType="string")
        cmds.setAttr(f"{obj_node}.{attr}", value, type="string")


def _remove_reference_by_namespace(namespace):
    """
    2.24.7: best-effort cleanup for _commit_cache_add — if a Shade asset
    gets referenced as part of the auto-match step but the cache attach
    then fails (missing OBJ group, AbcImport error), the code falls back
    to importing the cache with the default shader — but was leaving
    that just-created, now-unused Shade reference sitting in the scene
    untouched. It's a normal (trackable) asset reference so it wasn't
    literally invisible to Asset Manager, but it's a stray, unlinked
    duplicate the user never asked for and didn't attach anything to —
    exactly the kind of clutter that reads as "this is bringing in
    caches as default shade files instead of just attaching to the
    shade asset." Removes whatever reference populated `namespace`;
    silently no-ops if there's nothing there (namespace never actually
    got referenced, or was already cleaned up).

    2.24.12: no longer called from anywhere — Todd, correctly, pointed
    out this was exactly why repeat failed attempts never left 3
    distinct Shade references visible in the Outliner to inspect:
    each one got deleted the moment it failed, so every subsequent
    attempt just recomputed the same freed namespace instead of a new
    one, hiding the one thing that would show whether -connect is
    wiring onto the wrong (e.g. the first, already-successful) node
    instead of the fresh one it was actually given. Left defined, unused,
    for when the underlying repeat-attach bug is actually found and this
    cleanup is worth re-enabling.
    """
    nodes_in_namespace = cmds.ls(f"{namespace}:*", long=True) or []
    if not nodes_in_namespace:
        return
    try:
        ref_node = cmds.referenceQuery(nodes_in_namespace[0], referenceNode=True)
        cmds.file(referenceNode=ref_node, removeReference=True)
    except Exception:
        pass


def _import_cache_standalone(cache_file_path, cache_name):
    """
    2.24.9: Todd's Script Editor log pinned down the real cause behind
    "attaches once, then falls back to default shader every time after"
    — his screenshot showed the scene already had two bare, unnamespaced
    "OBJ"/"OBJ1" nodes (each with a "george_michael" child) left behind
    by earlier Default Shader fallback imports (2.20.0's
    IMPORT_CACHES_DEFAULT_SHADER_LABEL path / 2.24.2's
    _add_cache_default_shader — neither ever put the standalone import
    in a namespace). Once ANY such bare-named node exists anywhere in
    the scene, it's the most likely explanation for why a LATER
    `AbcImport(..., connect=obj_node)` attempt — even onto a totally
    different, correctly namespace-qualified target — silently connects
    nothing: AbcImport's -connect matches the archive's internal
    hierarchy onto the scene by NODE NAME, and once "george_michael" (or
    whatever the archive's child nodes are called) exists more than once
    anywhere in the scene, that name is no longer unique enough for
    Maya to resolve unambiguously, however cleanly namespaced the
    intended target itself is. This lines up with the exact evidence:
    the FIRST attach (a clean scene, nothing bare-named yet) worked;
    every attach after the first standalone fallback ran did not.

    Fix: standalone/Default-Shader imports now go into their own unique
    namespace (`_unique_reference_namespace(f"{cache_name}_default")`,
    reusing the same uniquification helper real asset references use)
    via Maya's ambient namespace context (`cmds.namespace(setNamespace=...)`)
    rather than landing bare at the scene root — so a fallback import
    can never again leave same-named nodes lying around to collide with
    a later real attach. UNCONFIRMED — this is the most concrete lead
    the evidence points to, but wasn't reproducible here without a live
    Maya session; if repeat attaches still fail after this, the exact
    new obj_node/error text in the warning is the next thing to send.

    Returns (new_nodes, namespace) — new_nodes is every new top-level
    node created by the import (still found via the existing
    before/after cmds.ls(assemblies=True) diff, now scoped to just this
    namespace's own new top-level nodes).
    """
    namespace = _unique_reference_namespace(f"{cache_name}_default")
    if not cmds.namespace(exists=namespace):
        cmds.namespace(add=namespace)
    previous_namespace = cmds.namespaceInfo(currentNamespace=True)
    cmds.namespace(setNamespace=namespace)
    try:
        before_nodes = set(cmds.ls(assemblies=True, long=True) or [])
        cmds.AbcImport(cache_file_path, mode="import")
        after_nodes = set(cmds.ls(assemblies=True, long=True) or [])
    finally:
        cmds.namespace(setNamespace=previous_namespace or ":")
    new_nodes = list(after_nodes - before_nodes)
    return new_nodes, namespace


def _tag_cache_standalone_nodes(new_nodes, shot_name, cache_name, filename=None):
    """
    2.24.7: caches imported with the default shader (no matching Shade
    asset, or the match failed to attach) were never tagged at all — the
    documented "known gap" since 2.20.1/2.24.2 — which made them
    genuinely invisible to Asset Manager's In Scene list and count, not
    just visually unlinked. That's very likely a real contributor to
    Todd's "not tracking caches properly in the count" report: any cache
    that fell back to the default shader simply vanished from Asset
    Manager's bookkeeping the moment it happened, with nothing in the
    panel to explain why the count looked wrong. Tags every new
    top-level node from a standalone AbcImport the same way a
    real attach does (_tag_cache_attachment), so
    _asset_manager_collect_cache_rows picks these up too — they'll show
    with no 🔗 link (correctly, since nothing's actually attached to a
    Shade asset) instead of not showing at all.

    2.24.8: also passes filename through to _tag_cache_attachment for
    consistency with the real-attach path (see CACHE_ATTR_FILE) — a
    standalone import doesn't go through the scratch-copy workaround, so
    its own AlembicNode's .abc_File is already accurate, but stamping it
    explicitly here too means both kinds of cache rows read their
    current version the exact same way rather than two different ones.
    """
    for node in new_nodes:
        try:
            _tag_cache_attachment(node, shot_name, cache_name, filename=filename)
        except Exception:
            pass


_CACHE_LINK_NAMESPACE_PATTERN = re.compile(
    rf"^(.+)_(?:{'|'.join(re.escape(t) for t in ASSET_TASK_SUFFIXES)})_v(\d+)$", re.IGNORECASE
)


def _shade_asset_namespace_and_label(obj_node):
    """
    2.24.5: given the node a cache is merged onto (obj_node, tagged via
    _tag_cache_attachment), figure out the Shade asset's reference
    namespace and a friendly display label ("georgeMichael v002"). Used
    by the Asset Manager panel to show which Shade asset a cache is
    attached to (Todd: "show which shade file is attached to which
    cache.. just to show they are linked"), and to find that asset's own
    In Scene row so removing it can cascade to its attached cache(s)
    ("if you want to remove a shade asset.. you dont remove the one
    attached to a cache" — well, you still can, but the cache comes with
    it now instead of being silently left dangling).

    Also drives the removal logic's "detach only, keep the geometry"
    vs. "delete the whole node" decision in _do_update — see that
    function's is_cache branch. So this must return a real namespace
    ONLY when obj_node is genuinely part of a REFERENCED Shade asset.

    2.31.7 BUG FIX: this used to treat ANY namespace on obj_node as
    proof of a Shade asset attachment — but standalone/default-shader
    cache imports have used their own namespace since 2.24.9
    (_import_cache_standalone, to avoid bare-name attach collisions;
    see that function's docstring), which this function never accounted
    for. Result: removing a standalone cache incorrectly took the
    detach-only path (delete the AlembicNode, clear tags) and left its
    geometry behind forever — Todd: "brought in 2 caches (different
    version numbers) and tried to remove the older one and it says it
    removed but it only removed the animation, not the object." Fixed
    by additionally requiring obj_node to actually be part of a
    REFERENCED file (cmds.referenceQuery isNodeReferenced) — a
    standalone cache's nodes are IMPORTED, not referenced, so this now
    correctly tells the two cases apart regardless of namespace.

    Returns (namespace, label) — both None if the node has no namespace
    at all, isn't actually referenced, or no longer exists (e.g. the
    Shade asset it was merged onto has since been removed by hand,
    outside Asset Manager).
    """
    if not obj_node or not cmds.objExists(obj_node):
        return None, None
    short_name = obj_node.split("|")[-1]
    parts = short_name.split(":")
    if len(parts) < 2:
        return None, None  # no namespace at all
    try:
        if not cmds.referenceQuery(obj_node, isNodeReferenced=True):
            return None, None  # namespaced but not referenced -> a standalone cache import, not a Shade asset
    except Exception:
        return None, None
    namespace = parts[-2]  # the namespace immediately containing this node
    match = _CACHE_LINK_NAMESPACE_PATTERN.match(namespace)
    label = f"{match.group(1)} v{match.group(2)}" if match else namespace
    return namespace, label


def _parse_cache_file_path(project_path, cache_file_path):
    """
    Given a cache file's full path, return (shot_name, cache_name) parsed
    back out of the standard shots/<shot>/anim/output/cache/<cache_name>.
    vNNN.abc layout, or (None, None) if it doesn't match. Used to tag a
    cache attachment from the Add Asset Cache picker, which only has the
    file path in hand (unlike Import Caches, which already knows the shot
    and cache name from its own dropdowns).
    """
    try:
        rel = os.path.relpath(cache_file_path, project_path).replace("\\", "/")
    except ValueError:
        return None, None  # different drive on Windows, can't make relative

    parts = rel.split("/")
    if len(parts) >= 6 and parts[0] == "shots" and parts[2:5] == ["anim", "output", "cache"]:
        shot_name = parts[1]
        match = CACHE_VERSIONED_FILE_PATTERN.match(parts[-1])
        cache_name = match.group(1) if match else None
        return shot_name, cache_name
    return None, None


# Used to redden the version dropdown when it's off the latest version,
# and to darken the "X" button while a row is staged for removal.
ASSET_MANAGER_OLD_COLOR = (0.5, 0.22, 0.22)
ASSET_MANAGER_UPDATED_COLOR = (0.24, 0.45, 0.26)


def _asset_manager_resolve_asset_task(project_path, namespace, file_path):
    """
    Figure out which asset/task a loaded reference belongs to. Tries the
    namespace first (assets are usually referenced with a namespace that
    matches the asset name), then falls back to parsing the filename's
    "<asset>_<task>.vNNN.ext" pattern (same convention used elsewhere in
    this file — see guess_asset_name_from_current_scene). This doesn't
    depend on the file living at any particular depth under the project,
    so it still works even if the reference was loaded from an unusual
    location, as long as an assets/<type>/<asset_name>/ folder exists.
    """
    filename = os.path.basename(file_path)
    stem = os.path.splitext(filename)[0]
    stem = re.sub(r"\.v\d+$", "", stem, flags=re.IGNORECASE)

    candidates = []
    if namespace:
        candidates.append(namespace)
    for task in ASSET_TASK_SUFFIXES:
        suffix = f"_{task}"
        if stem.lower().endswith(suffix):
            candidates.append(stem[: -len(suffix)])
            break

    for asset_name in candidates:
        asset_dir = find_asset_folder(project_path, asset_name)
        if not asset_dir:
            continue
        for task in ASSET_TASK_SUFFIXES:  # model/rig/lookdev/fx — texture isn't referenceable
            source_dir = asset_task_source_dir(asset_dir, task)
            if os.path.isfile(os.path.join(source_dir, filename)):
                return asset_name, task
            # The exact loaded file may since have been deleted/moved, but
            # a matching "<asset>_<task>" stub still tells us the task.
            if stem == f"{asset_name}_{task}":
                return asset_name, task

    return None, None


def _asset_manager_collect_rows(project_path):
    """Gather one row per top-level reference currently loaded in the scene."""
    rows = []
    for ref_node in cmds.ls(references=True):
        try:
            file_path = cmds.referenceQuery(ref_node, filename=True, withoutCopyNumber=True)
        except RuntimeError:
            continue  # stale/unloaded reference node

        try:
            namespace = cmds.referenceQuery(ref_node, namespace=True).lstrip(":")
        except RuntimeError:
            namespace = ""

        asset_name, task_name = _asset_manager_resolve_asset_task(project_path, namespace, file_path)
        filename = os.path.basename(file_path)
        match = VERSIONED_FILE_PATTERN.match(filename)
        # Keep the version digits as the raw matched string (e.g. "002"),
        # not an int — converting to int and back would drop the leading
        # zeros and produce a label like "v2" that doesn't match the
        # zero-padded "v002" label used everywhere else, showing up as a
        # bogus duplicate entry in the version dropdown.
        current_version_label = f"v{match.group(2)}" if match else None

        if asset_name and task_name:
            available_versions = get_asset_task_versions(project_path, asset_name, task_name)
        else:
            available_versions = [filename]  # can't resolve on disk; just offer what's loaded

        rows.append(
            {
                "ref_node": ref_node,
                "file_path": file_path,
                "filename": filename,
                "namespace": namespace,
                "asset_name": asset_name,
                "task_name": task_name,
                "current_version_label": current_version_label,
                "available_versions": available_versions,  # newest first
                "is_import": False,
            }
        )

    rows.extend(_asset_manager_collect_imported_rows(project_path, {r["namespace"] for r in rows if r["namespace"]}))
    rows.extend(_asset_manager_collect_cache_rows(project_path))

    def sort_key(row):
        order = (
            ASSET_MANAGER_TASK_ORDER.index(row["task_name"])
            if row["task_name"] in ASSET_MANAGER_TASK_ORDER
            else len(ASSET_MANAGER_TASK_ORDER)
        )
        display_name = row["asset_name"] or row["namespace"] or row["filename"]
        return (order, display_name)

    rows.sort(key=sort_key)
    return rows


def _asset_manager_collect_imported_rows(project_path, referenced_namespaces):
    """
    Find namespaces that match this pipeline's "<asset>_<task>_v<NNN>"
    convention but aren't backed by a live reference anymore — i.e. an
    asset that was already switched from Reference to Import (this
    session or a previous one, since it survives file save). Build a
    synthetic row for each so Asset Manager keeps listing/tracking it
    even though it's no longer a reference.

    2.28.1: Todd — after switching a row to "Load [tracked]" via the new
    2.28.0 Import As dropdown, the row still showed up (correctly
    "tracked"), but its version number disappeared, showing "-" instead
    -- this defeated the point of calling it "tracked". Root cause:
    these synthetic rows always hardcoded available_versions to [] with
    a "not swappable once imported" comment, and _panel_version_labels
    (fed by available_versions) is also what the version combo displays,
    not just what it lets you pick -- so an empty list blanked the
    number entirely instead of just disabling the dropdown (which
    "is_import" already does on its own, independently of this). Now
    populated via get_asset_task_versions so the current version number
    still shows; the combo itself stays disabled for import rows
    regardless, same as before.
    """
    rows = []
    for ns in cmds.namespaceInfo(listOnlyNamespaces=True, recurse=False) or []:
        if ns in referenced_namespaces or ns in ("UI", "shared"):
            continue

        match = re.match(r"^(.+)_v(\d+)$", ns)
        if not match:
            continue
        stem, version_digits = match.group(1), match.group(2)

        asset_name = None
        task_name = None
        for task in ASSET_TASK_SUFFIXES:
            suffix = f"_{task}"
            if stem.endswith(suffix):
                asset_name = stem[: -len(suffix)]
                task_name = task
                break
        if not asset_name:
            continue  # doesn't match our naming convention — not ours to track

        # A namespace can outlive everything that was ever inside it —
        # Maya doesn't auto-delete an empty namespace once its last node
        # is removed. Checking for ANY leftover member wasn't enough
        # (fixed 2.13.21, still didn't work): imported files also bring
        # in non-DAG nodes — shading networks, sets, unitConversion nodes
        # — that can survive even after every visible piece of geometry
        # under the namespace has been deleted, so `ls(f"{ns}:*")` still
        # came back non-empty. Require an actual DAG object (a transform
        # or shape — the kind of thing that would actually show up in
        # the Outliner) instead of just any namespace member.
        if not cmds.ls(f"{ns}:*", dagObjects=True):
            continue

        rows.append(
            {
                "ref_node": None,
                "file_path": None,
                "filename": f"{stem}.v{version_digits}.ma",
                "namespace": ns,
                "asset_name": asset_name,
                "task_name": task_name,
                "current_version_label": f"v{version_digits}",
                # 2.28.1: populated so the version number still displays
                # (see docstring above) -- the version combo stays
                # disabled for import rows regardless, via "is_import".
                "available_versions": get_asset_task_versions(project_path, asset_name, task_name),
                "is_import": True,
            }
        )

    return rows


def _asset_manager_collect_cache_rows(project_path):
    """
    One row per node in the scene tagged (via _tag_cache_attachment) with
    a cache merged onto it — every attach done through the Add Asset
    Cache picker or the Import Caches window (2.22.0). Lets Asset Manager
    show attached caches alongside real asset references, and version
    them up the same way: pick a newer entry in the Version dropdown and
    hit Apply, which re-runs _attach_cache_to_node onto the newer file
    (see the Apply-time "is_cache_row" branch in show_asset_manager_window).
    """
    rows = []
    for node in cmds.ls(long=True, type="transform"):
        if not cmds.attributeQuery(CACHE_ATTR_SHOT, node=node, exists=True):
            continue

        try:
            shot_name = cmds.getAttr(f"{node}.{CACHE_ATTR_SHOT}") or ""
            cache_name = cmds.getAttr(f"{node}.{CACHE_ATTR_NAME}") or ""
        except Exception:
            continue
        if not shot_name or not cache_name:
            continue

        available_versions = get_shot_cache_versions(project_path, shot_name, cache_name)

        # 2.24.8: prefer the explicitly-tagged CACHE_ATTR_FILE (stamped
        # by _tag_cache_attachment at attach time) over reading the
        # connected AlembicNode's .abc_File — since _attach_cache_to_node
        # now imports from a throwaway scratch copy (see its 2.24.8
        # note), .abc_File points at that scratch path, not a real
        # versioned filename, and can no longer be parsed for the
        # version label. Falls back to the old .abc_File-parsing
        # behavior only for nodes tagged before CACHE_ATTR_FILE existed
        # (or where it's missing/empty for any other reason), so a scene
        # someone attached a cache in before 2.24.8 still shows *something*
        # rather than a blank version.
        current_filename = None
        try:
            current_filename = cmds.getAttr(f"{node}.{CACHE_ATTR_FILE}") or None
        except Exception:
            current_filename = None
        if not current_filename:
            alembic_nodes = _find_connected_alembic_nodes(node)
            if alembic_nodes:
                try:
                    current_path = cmds.getAttr(f"{alembic_nodes[0]}.abc_File")
                    current_filename = os.path.basename(current_path) if current_path else None
                except Exception:
                    current_filename = None

        current_version_label = None
        if current_filename:
            match = CACHE_VERSIONED_FILE_PATTERN.match(current_filename)
            current_version_label = f"v{match.group(2)}" if match else current_filename

        # 2.24.5: which Shade asset (if any) this cache is actually
        # merged onto — see _shade_asset_namespace_and_label.
        attached_namespace, attached_asset_label = _shade_asset_namespace_and_label(node)

        rows.append(
            {
                "ref_node": None,
                "file_path": None,
                "filename": current_filename or "",
                "namespace": "",
                "attached_namespace": attached_namespace,
                "attached_asset_label": attached_asset_label,
                # Just the cache name — Todd: "clean up the cache name in
                # the asset manager.. the shade attach doesnt need to be
                # there.. that line is for caches only." (previously
                # "<cache_name> → <node short name>", e.g.
                # "georgeMichael_anim → georgeMichael_lookdev_v002:OBJ").
                # Which node it's merged onto is still tracked internally
                # (cache_obj_node below) — just not shown in this column.
                "asset_name": cache_name,
                "task_name": ASSET_MANAGER_CACHE_TASK,
                "current_version_label": current_version_label,
                "available_versions": available_versions,  # newest first
                "is_import": False,
                "is_cache_row": True,
                "cache_obj_node": node,
                "cache_shot_name": shot_name,
                "cache_name": cache_name,
            }
        )

    return rows


def clean_rig_asset(*_args):
    """
    "Clean Rig Asset" menu command. Straight rename ("...Deformed" ->
    "...") ran into a Maya issue, so this does it as a two-step swap
    instead:
      1. Whatever's currently sitting on the target name -> "<target>Orig"
         (move it out of the way first, freeing up its name)
      2. "<target>Deformed" -> "<target>"     (deformed output takes
         over the now-vacant name)

    2.31.5: Todd — the original version assumed every shape name ended
    in the literal suffix "Shape" (e.g. "nameShape"/"nameShapeDeformed"),
    but Maya's default shape naming doesn't reliably follow that —
    e.g. a transform named "cube1" gets a shape named "cubeShape1", not
    "cube1Shape", so a deformed variant of it comes out as
    "cubeShape1Deformed" (the trailing digit sits BEFORE "Deformed", not
    immediately after the word "Shape"). Matching by peeling a fixed
    "Shape"/"ShapeDeformed" suffix off missed that entirely. Fixed by no
    longer assuming anything about shape-name structure at all: any
    shape node whose name ends in "Deformed" gets that literal suffix
    stripped to derive its target name directly — whatever the rest of
    the name looks like — rather than trying to reconstruct a "base"
    name and re-derive both sibling names from it.

    A lone "...Deformed" shape with nothing already on its target name
    is just renamed straight there (nothing to move aside). Target-name
    lookup is scoped to the deformed shape's own parent transform (via
    listRelatives), not a name match across the whole selection — so
    two different rig assets selected together that happen to share an
    identical local shape name no longer collide with each other (a
    latent issue in the old base-name-dict approach too).
    """
    selection = cmds.ls(selection=True, long=True) or []
    if not selection:
        cmds.warning("Please select asset(s) before running Clean Rig Asset.")
        return

    shapes = set(cmds.listRelatives(selection, allDescendents=True, type="shape", fullPath=True) or [])
    shapes.update(node for node in selection if cmds.objectType(node, isType="shape"))

    deformed_shapes = sorted(s for s in shapes if s.split("|")[-1].endswith("Deformed"))

    renamed = 0
    for deformed_path in deformed_shapes:
        if not cmds.objExists(deformed_path):
            continue

        short_name = deformed_path.split("|")[-1]
        target_name = short_name[: -len("Deformed")]
        if not target_name:
            continue

        parent = cmds.listRelatives(deformed_path, parent=True, fullPath=True)
        orig_path = None
        if parent:
            candidate = f"{parent[0]}|{target_name}"
            if cmds.objExists(candidate) and candidate != deformed_path:
                orig_path = candidate
        elif cmds.objExists(target_name) and target_name != deformed_path:
            orig_path = target_name

        if orig_path:
            try:
                cmds.rename(orig_path, f"{target_name}Orig")
            except Exception as e:
                cmds.warning(f"Could not rename {target_name}: {e}")
                continue

        try:
            cmds.rename(deformed_path, target_name)
            renamed += 1
        except Exception as e:
            cmds.warning(f"Could not rename {short_name}: {e}")

    if renamed:
        print(f"Clean Rig Asset: cleaned {renamed} shape(s).")
    else:
        cmds.warning('No "...Deformed" shape nodes were found in the selection.')


def show_asset_manager_add_window(project_path, on_close=None):
    """
    "+ Add Asset" flow for Asset Manager: same interaction as the Asset
    Rig Picker (asset dropdown + version dropdown, Add Asset / Add and
    Keep Open / Close), but with a Type dropdown on top so any task type
    can be added from one window instead of a separate picker per type.

    Type also offers "Cache" (ASSET_MANAGER_CACHE_TASK) — not a real asset
    task, it pulls from shots/<shot>/anim/output/cache instead. Picking
    Cache repurposes the row from Name/Ver/Mode to Shot/Cache Name/Ver:
    the 2nd dropdown lists shots, the 3rd (normally Mode, N/A for caches)
    is repurposed to list that shot's cache name stubs (one per object
    Export Cache has ever written for it, e.g. "georgeMichael_anim",
    "camera_anim" — see export_selection_to_cache), and the 4th (Ver)
    lists that specific cache name's versions, newest first, pre-selected
    to the latest rather than forcing a placeholder pick (every other
    dropdown here forces an explicit choice; Ver is the one exception,
    same reasoning as Mode defaulting to "Reference"). Add opens a
    separate small popup (show_cache_shade_picker_window) to pick a Shade
    asset to merge the cache onto, rather than adding directly.
    """
    if cmds.window(ASSET_MANAGER_ADD_WINDOW, exists=True):
        cmds.deleteUI(ASSET_MANAGER_ADD_WINDOW)

    window = cmds.window(ASSET_MANAGER_ADD_WINDOW, title="Add Asset", sizeable=False, width=400)
    cmds.columnLayout(adjustableColumn=True, columnAlign="left", rowSpacing=6, columnOffset=("both", 12))

    cmds.text(label="")  # top spacer
    cmds.text(label="Add Asset", font="boldLabelFont", align="left")
    cmds.separator(height=10, style="in")

    # Type, asset, mode/cache-name, and version dropdowns all in one row, sitting
    # close together (no columnWidth cells — those left dead space when a
    # dropdown's actual rendered size was smaller than its assigned
    # column; columnAttach4/columnOffset4 instead sizes each column to
    # its control's own width plus a small fixed gap).
    cmds.rowLayout(
        numberOfColumns=4,
        columnAttach4=("left", "left", "left", "left"),
        columnOffset4=(0, 8, 8, 8),
    )
    # Row order is Type / Name / Mode / Ver for a real asset type, or
    # Type / Shot / Cache Name / Ver when Type=Cache (Mode doesn't apply
    # to caches, so that 3rd slot is repurposed rather than shown
    # disabled — see refresh_fourth_dropdown).
    #
    # Every dropdown opens on an unselected placeholder ("Type"/"Name"/
    # "Shot"/"Cache Name") rather than defaulting to the first real entry
    # — Todd wants the tool to force an explicit choice each time it's
    # opened, not silently pre-pick something. Once the user picks a real
    # value it stays picked for the rest of this window's life;
    # placeholders only come back if the window is reopened. Mode and Ver
    # are the two exceptions: Mode defaults to "Reference" (the
    # original/most common behavior) and, for Cache only, Ver defaults to
    # the latest version once a cache name is picked (Todd's explicit
    # ask — see refresh_versions).
    ASSET_MANAGER_TYPE_PLACEHOLDER = "Type"
    ASSET_MANAGER_NAME_PLACEHOLDER = "Name"
    ASSET_MANAGER_SHOT_PLACEHOLDER = "Shot"
    ASSET_MANAGER_CACHE_NAME_PLACEHOLDER = "Cache Name"
    ASSET_MANAGER_VER_PLACEHOLDER = "Ver"
    ASSET_MANAGER_ADD_MODES = ("Load", "Import", "Reference")

    # ASSET_TASK_SUFFIXES (model/rig/lookdev/fx) — texture isn't
    # referenceable, so it's never offered here — plus the synthetic Cache
    # entry appended last.
    type_dropdown = cmds.optionMenu(width=100)
    cmds.menuItem(label=ASSET_MANAGER_TYPE_PLACEHOLDER, parent=type_dropdown)
    for task in ASSET_TASK_SUFFIXES:
        cmds.menuItem(label=ASSET_MANAGER_TASK_LABELS[task], parent=type_dropdown)
    cmds.menuItem(label=ASSET_MANAGER_CACHE_LABEL, parent=type_dropdown)
    asset_dropdown = cmds.optionMenu(width=140)
    # 3rd dropdown: normally Mode (Load/Import/Reference) for a real asset
    # type; repurposed to Cache Name (which object's cache, for the
    # selected shot) when Type=Cache — see refresh_fourth_dropdown.
    fourth_dropdown = cmds.optionMenu(width=110)
    version_dropdown = cmds.optionMenu(width=100)
    cmds.setParent("..")

    version_lookup = {}  # version label -> filename, newest first

    def current_task_name():
        label = cmds.optionMenu(type_dropdown, query=True, value=True)
        if label == ASSET_MANAGER_TYPE_PLACEHOLDER:
            return None
        if label == ASSET_MANAGER_CACHE_LABEL:
            return ASSET_MANAGER_CACHE_TASK
        return next(t for t in ASSET_TASK_SUFFIXES if ASSET_MANAGER_TASK_LABELS[t] == label)

    def refresh_versions(*_args):
        for item in cmds.optionMenu(version_dropdown, query=True, itemListLong=True) or []:
            cmds.deleteUI(item)
        version_lookup.clear()
        cmds.menuItem(label=ASSET_MANAGER_VER_PLACEHOLDER, parent=version_dropdown)

        task_name = current_task_name()
        if not task_name:
            return

        if task_name == ASSET_MANAGER_CACHE_TASK:
            shot_name = cmds.optionMenu(asset_dropdown, query=True, value=True)
            cache_name = cmds.optionMenu(fourth_dropdown, query=True, value=True)
            if shot_name == ASSET_MANAGER_SHOT_PLACEHOLDER or cache_name == ASSET_MANAGER_CACHE_NAME_PLACEHOLDER:
                return
            filenames = get_shot_cache_versions(project_path, shot_name, cache_name)
            pattern = CACHE_VERSIONED_FILE_PATTERN
        else:
            asset_name = cmds.optionMenu(asset_dropdown, query=True, value=True)
            if asset_name == ASSET_MANAGER_NAME_PLACEHOLDER:
                return
            filenames = get_asset_task_versions(project_path, asset_name, task_name)
            pattern = VERSIONED_FILE_PATTERN

        for filename in filenames:
            match = pattern.match(filename)
            label = f"v{match.group(2)}" if match else filename
            version_lookup[label] = filename
            cmds.menuItem(label=label, parent=version_dropdown)

        # Every other dropdown here forces an explicit pick (see the note
        # above ASSET_MANAGER_TYPE_PLACEHOLDER), but for Cache the version
        # is pre-selected to the latest — Todd's explicit ask, since by
        # the time you've picked a shot and a cache name you almost
        # always want the newest version of it, not a forced extra click.
        if task_name == ASSET_MANAGER_CACHE_TASK and filenames:
            latest_match = pattern.match(filenames[0])
            latest_label = f"v{latest_match.group(2)}" if latest_match else filenames[0]
            cmds.optionMenu(version_dropdown, edit=True, value=latest_label)

    def refresh_fourth_dropdown(*_args):
        """Repopulate the 3rd (Mode / Cache Name) dropdown for the current task, then cascade to versions."""
        for item in cmds.optionMenu(fourth_dropdown, query=True, itemListLong=True) or []:
            cmds.deleteUI(item)

        task_name = current_task_name()
        if task_name == ASSET_MANAGER_CACHE_TASK:
            cmds.menuItem(label=ASSET_MANAGER_CACHE_NAME_PLACEHOLDER, parent=fourth_dropdown)
            shot_name = cmds.optionMenu(asset_dropdown, query=True, value=True)
            if shot_name != ASSET_MANAGER_SHOT_PLACEHOLDER:
                for cache_name in get_shot_cache_names(project_path, shot_name):
                    cmds.menuItem(label=cache_name, parent=fourth_dropdown)
            cmds.optionMenu(fourth_dropdown, edit=True, enable=True)
        else:
            for mode in ASSET_MANAGER_ADD_MODES:
                cmds.menuItem(label=mode, parent=fourth_dropdown)
            cmds.optionMenu(fourth_dropdown, edit=True, value="Reference", enable=bool(task_name))

        refresh_versions()

    def refresh_assets(*_args):
        for item in cmds.optionMenu(asset_dropdown, query=True, itemListLong=True) or []:
            cmds.deleteUI(item)

        task_name = current_task_name()
        if task_name == ASSET_MANAGER_CACHE_TASK:
            cmds.menuItem(label=ASSET_MANAGER_SHOT_PLACEHOLDER, parent=asset_dropdown)
            for shot_name in list_existing_shots(project_path):
                cmds.menuItem(label=shot_name, parent=asset_dropdown)
        else:
            cmds.menuItem(label=ASSET_MANAGER_NAME_PLACEHOLDER, parent=asset_dropdown)
            if task_name:
                for asset_name in list_assets_with_task(project_path, task_name):
                    cmds.menuItem(label=asset_name, parent=asset_dropdown)

        refresh_fourth_dropdown()

    cmds.optionMenu(type_dropdown, edit=True, changeCommand=refresh_assets)
    cmds.optionMenu(asset_dropdown, edit=True, changeCommand=refresh_fourth_dropdown)
    cmds.optionMenu(
        fourth_dropdown,
        edit=True,
        changeCommand=lambda *_a: refresh_versions() if current_task_name() == ASSET_MANAGER_CACHE_TASK else None,
    )
    refresh_assets()

    cmds.separator(height=10, style="in")

    def do_add():
        task_name = current_task_name()
        if not task_name:
            cmds.warning("Select a type first.")
            return

        is_cache = task_name == ASSET_MANAGER_CACHE_TASK
        name_placeholder = ASSET_MANAGER_SHOT_PLACEHOLDER if is_cache else ASSET_MANAGER_NAME_PLACEHOLDER
        picker_noun = "shots with cache files" if is_cache else f"assets with {task_name} files"

        name_value = cmds.optionMenu(asset_dropdown, query=True, value=True)
        if name_value == name_placeholder:
            # Only the placeholder itself in the list (no real entries
            # underneath it) means there's nothing for this type at all;
            # otherwise the user just hasn't picked one yet.
            items = cmds.optionMenu(asset_dropdown, query=True, itemListLong=True) or []
            if len(items) <= 1:
                cmds.warning(f"No {picker_noun} found.")
            else:
                cmds.warning("Select a shot first." if is_cache else "Select an asset name first.")
            return

        if is_cache:
            cache_name_value = cmds.optionMenu(fourth_dropdown, query=True, value=True)
            if cache_name_value == ASSET_MANAGER_CACHE_NAME_PLACEHOLDER:
                items = cmds.optionMenu(fourth_dropdown, query=True, itemListLong=True) or []
                if len(items) <= 1:
                    cmds.warning(f'No cached objects found for shot "{name_value}".')
                else:
                    cmds.warning("Select a cache name first.")
                return

        version_label = cmds.optionMenu(version_dropdown, query=True, value=True)
        if version_label == ASSET_MANAGER_VER_PLACEHOLDER:
            cmds.warning("Select a version first.")
            return
        filename = version_lookup.get(version_label)
        if not filename:
            cmds.warning("Could not resolve the selected version.")
            return

        if is_cache:
            cache_file_path = os.path.join(get_shot_cache_dir(project_path, name_value), filename)
            show_cache_shade_picker_window(project_path, cache_file_path)
            return

        asset_name = name_value
        asset_dir = find_asset_folder(project_path, asset_name)
        if not asset_dir:
            cmds.warning(f"Could not find asset folder for {asset_name}.")
            return

        mode = cmds.optionMenu(fourth_dropdown, query=True, value=True)
        file_path = os.path.join(asset_task_source_dir(asset_dir, task_name), filename)
        namespace = namespace_for_versioned_file(filename)
        try:
            if mode == "Reference":
                # Explicit namespace matching the full versioned filename,
                # e.g. "harbor_env_model_v014" — see namespace_for_versioned_file.
                cmds.file(file_path, reference=True, namespace=namespace)
                print(f"Referenced: {file_path}")
                # 2.24.16: Todd — a Shade asset added on its own here should
                # end up grouped exactly the same way one does when it comes
                # in through the cache-attach flow (_attach_cache_to_node's
                # 2.24.15 fix), so it's never left sitting at DAG root next
                # to another Shade asset's OBJ node. Only lookdev (Shade)
                # matters here — that's the only task cache attach ever
                # targets — and only Reference/Import modes have an
                # OBJ node with a namespace to group at all ("Load" merges
                # flat with no namespace, nothing to group).
                if task_name == "lookdev":
                    _ensure_obj_node_grouped(f"{namespace}:OBJ", asset_name=asset_name, task_name=task_name)
            elif mode == "Import":
                cmds.file(
                    file_path,
                    i=True,
                    namespace=namespace,
                    ignoreVersion=True,
                )
                print(f"Imported (namespaced): {file_path}")
                if task_name == "lookdev":
                    _ensure_obj_node_grouped(f"{namespace}:OBJ", asset_name=asset_name, task_name=task_name)
            else:  # "Load" — import flat into the scene, no namespace at all
                cmds.file(
                    file_path,
                    i=True,
                    namespace=":",
                    mergeNamespacesOnClash=True,
                    ignoreVersion=True,
                )
                print(f"Loaded (no namespace): {file_path}")
        except Exception as e:
            cmds.warning(f"Could not {mode.lower()} {file_path}: {e}")

    def on_add_button(*_args):
        # Add, then close the window — the common case (add one thing and
        # get back to work).
        do_add()
        cmds.deleteUI(window)
        if on_close:
            on_close()

    def on_add_and_keep_open_button(*_args):
        # Add without closing — lets the user add several assets in a row
        # before dismissing the popup.
        do_add()

    def on_cancel_button(*_args):
        cmds.deleteUI(window)
        if on_close:
            on_close()

    # Add / Add and Keep Open / Cancel sit snug together, right-justified —
    # using the same adjustable-spacer trick as Asset Manager's own
    # Apply/Close row, so they stay pinned to the true right edge
    # regardless of window size. Anything already added via either Add
    # button stays added — Cancel only discards the window itself, not
    # staged-but-unapplied work (there isn't any — Add commits immediately
    # per click).
    cmds.columnLayout(adjustableColumn=True)
    cmds.rowLayout(
        numberOfColumns=4,
        columnWidth4=(10, 70, 150, 90),
        adjustableColumn=1,
        columnAlign4=("left", "right", "right", "right"),
    )
    cmds.text(label="")
    cmds.button(label="Add", width=70, command=on_add_button)
    cmds.button(label="Add and Keep Open", width=150, command=on_add_and_keep_open_button)
    cmds.button(label="Cancel", width=90, command=on_cancel_button)
    cmds.setParent("..")
    cmds.setParent("..")

    cmds.text(label="")  # bottom spacer

    cmds.showWindow(window)


CACHE_SHADE_PICKER_WINDOW = "cacheShadePickerWindow"


def show_cache_shade_picker_window(project_path, cache_file_path, on_close=None):
    """
    Second step of adding a Cache asset: pick a published Shade asset
    (name + version) to attach the cache to. On Import: references that
    Shade asset in, selects its "OBJ" root node (the group Setup Scene
    creates for every lookdev scene), then Alembic-imports the cache
    connected onto that selection's matching-named hierarchy.

    Fixed in 2.21.3 — see the comment in on_import() below for what was
    actually wrong (AbcImport's -reparent flag, not -connect).

    on_close: optional callback fired after the window closes, whether
    that's from a successful Import or hitting Cancel.

    (2.23.2: the new PySide Asset Manager panel (show_asset_manager_panel)
    no longer routes cache-adds through this popup at all — it auto-
    matches a same-named Shade asset (or falls back to a default shader)
    with no dialog, per Todd's ask to simplify that flow. This window is
    still used by the old cmds-based Asset Manager's Add Asset Mode flow,
    so it's kept as-is rather than removed.)
    """
    if cmds.window(CACHE_SHADE_PICKER_WINDOW, exists=True):
        cmds.deleteUI(CACHE_SHADE_PICKER_WINDOW)

    window = cmds.window(CACHE_SHADE_PICKER_WINDOW, title="Pick Shade Asset", sizeable=False, width=340)
    cmds.columnLayout(adjustableColumn=True, columnAlign="left", rowSpacing=6, columnOffset=("both", 12))

    cmds.text(label="")  # top spacer
    cmds.text(label="Pick Shade Asset for Cache", font="boldLabelFont", align="left")
    cmds.text(label=os.path.basename(cache_file_path), align="left", enable=False)
    cmds.separator(height=10, style="in")

    NAME_PLACEHOLDER = "Name"
    VER_PLACEHOLDER = "Ver"

    cmds.rowLayout(numberOfColumns=2, columnAttach2=("left", "left"), columnOffset2=(0, 8))
    asset_dropdown = cmds.optionMenu(width=160)
    version_dropdown = cmds.optionMenu(width=110)
    cmds.setParent("..")

    version_lookup = {}  # version label -> filename, newest first

    def refresh_versions(*_args):
        for item in cmds.optionMenu(version_dropdown, query=True, itemListLong=True) or []:
            cmds.deleteUI(item)
        version_lookup.clear()

        asset_name = cmds.optionMenu(asset_dropdown, query=True, value=True)
        cmds.menuItem(label=VER_PLACEHOLDER, parent=version_dropdown)
        if asset_name == NAME_PLACEHOLDER:
            return
        for filename in get_asset_task_versions(project_path, asset_name, "lookdev"):
            match = VERSIONED_FILE_PATTERN.match(filename)
            label = f"v{match.group(2)}" if match else filename
            version_lookup[label] = filename
            cmds.menuItem(label=label, parent=version_dropdown)

    cmds.menuItem(label=NAME_PLACEHOLDER, parent=asset_dropdown)
    for asset_name in list_assets_with_task(project_path, "lookdev"):
        cmds.menuItem(label=asset_name, parent=asset_dropdown)
    cmds.optionMenu(asset_dropdown, edit=True, changeCommand=refresh_versions)
    refresh_versions()

    cmds.separator(height=10, style="in")

    def on_import(*_args):
        asset_name = cmds.optionMenu(asset_dropdown, query=True, value=True)
        if asset_name == NAME_PLACEHOLDER:
            cmds.warning("Select a Shade asset first.")
            return
        version_label = cmds.optionMenu(version_dropdown, query=True, value=True)
        if version_label == VER_PLACEHOLDER:
            cmds.warning("Select a version first.")
            return
        filename = version_lookup.get(version_label)
        if not filename:
            cmds.warning("Could not resolve the selected version.")
            return

        asset_dir = find_asset_folder(project_path, asset_name)
        if not asset_dir:
            cmds.warning(f"Could not find asset folder for {asset_name}.")
            return

        shade_file_path = os.path.join(asset_task_source_dir(asset_dir, "lookdev"), filename)
        namespace = namespace_for_versioned_file(filename)
        try:
            cmds.file(shade_file_path, reference=True, namespace=namespace)
            print(f"Referenced: {shade_file_path}")
        except Exception as e:
            cmds.warning(f"Could not reference {shade_file_path}: {e}")
            return

        obj_node = f"{namespace}:OBJ"
        if not cmds.objExists(obj_node):
            cmds.warning(
                f'Referenced "{asset_name}" but could not find its "OBJ" group ({obj_node}) — '
                "cache was not imported. (Setup Scene creates OBJ for lookdev scenes — "
                "this asset may predate that, or use a different top group name.)"
            )
            cmds.deleteUI(window)
            return

        try:
            # Fixed in 2.21.3 — this used to pass reparent=obj_node, which
            # is NOT Maya's "Import Under Current Selection > Merge"
            # behavior: -reparent creates a brand-new copy of the whole
            # Alembic hierarchy as new child nodes under obj_node, sitting
            # alongside the Shade asset's actual geo rather than driving
            # it — which is why Todd saw it "not working well" (duplicate
            # geo, nothing actually merged onto the referenced asset).
            # -connect is the real merge flag: it walks obj_node's existing
            # hierarchy, finds nodes whose names match the Alembic file's
            # hierarchy, and connects the cache's animation directly onto
            # those existing nodes instead of creating new ones — no new
            # nodes appear, the referenced Shade geo just starts moving.
            # 2.22.0: routed through the shared _attach_cache_to_node
            # helper (same one Import Caches uses) so this is also
            # tagged via _tag_cache_attachment — that's what lets Asset
            # Manager find this attachment again and list/version it.
            _attach_cache_to_node(cache_file_path, obj_node, asset_name=asset_name)
            shot_name, cache_name = _parse_cache_file_path(project_path, cache_file_path)
            if shot_name and cache_name:
                _tag_cache_attachment(obj_node, shot_name, cache_name, filename=os.path.basename(cache_file_path))
            print(f"Imported cache: {cache_file_path} -> connected onto {obj_node}")
        except Exception as e:
            cmds.warning(f"Could not import cache {cache_file_path}: {e}")

        cmds.deleteUI(window)
        if on_close:
            on_close()

    def on_cancel(*_args):
        cmds.deleteUI(window)
        if on_close:
            on_close()

    cmds.columnLayout(adjustableColumn=True, columnAlign="center")
    cmds.rowLayout(numberOfColumns=2, columnAttach2=("both", "both"), columnOffset2=(0, 8))
    cmds.button(label="Import", width=85, command=on_import)
    cmds.button(label="Cancel", width=85, command=on_cancel)
    cmds.setParent("..")
    cmds.setParent("..")

    cmds.text(label="")  # bottom spacer

    cmds.showWindow(window)


def show_asset_manager_window():
    """
    (2.23.0: superseded as the "Asset Manager" menu item's target by the
    new PySide dock panel, show_asset_manager_panel — see the big comment
    block above that panel's code, right after this function, for the
    Claude Design mockup this was overhauled from and the rollback note.
    This function itself is untouched and still fully working standalone
    — it's just no longer what the menu opens.)

    Table of every reference currently loaded in the scene, plus any
    asset previously switched to Import (still tracked via its
    namespace even though it's no longer a live reference). Change a
    row's version, toggle it to Import, or mark it for removal, then hit
    Apply — or Close to throw away everything staged.
    """
    project_path = get_current_project()
    if not project_path:
        return

    rows = _asset_manager_collect_rows(project_path)

    if cmds.window(ASSET_MANAGER_WINDOW, exists=True):
        cmds.deleteUI(ASSET_MANAGER_WINDOW)

    # 2.22.3 — the 2.22.2 sizeable=False fix wasn't enough on its own:
    # Maya remembers a named window's last size/position via windowPref
    # and silently reapplies it on the NEXT open, regardless of the
    # width= passed to cmds.window() here — so Todd's earlier manual
    # drag-wide was still being restored every time, sizeable=False or
    # not (it only blocks resizing AFTER open, it doesn't stop the
    # remembered geometry from being used to open it in the first
    # place). Clearing that saved pref before creating the window forces
    # it back to this window's actual fixed width every time.
    if cmds.windowPref(ASSET_MANAGER_WINDOW, exists=True):
        cmds.windowPref(ASSET_MANAGER_WINDOW, remove=True)

    # Column widths for the table — EVERY column here is a hard fixed
    # pixel width now (2.22.4, Todd: "this isnt working.. every column
    # should be a fixed size"). 2.22.2/2.22.3 tried to get a fixed look
    # by stopping the WINDOW from being resized, while still using
    # Maya's adjustableColumn trick internally (one column marked to
    # stretch and absorb any leftover width) — that's an inherently
    # elastic layout, so any mismatch between the window's actual width
    # and the sum of the fixed columns still shows up as dead space.
    # Removed entirely below: no rowLayout in this window uses
    # adjustableColumn anymore, and TABLE_WIDTH is computed from the
    # column widths themselves and used to size the window and every
    # other row (the "+Add Asset" row, the bottom button row) to match
    # exactly — nothing left that can stretch or drift out of alignment.
    column_widths = (24, 70, 220, 110, 60, 90)
    add_asset_width = 110
    TABLE_WIDTH = sum(column_widths)  # 574
    OUTER_MARGIN = 12  # matches columnOffset=("both", 12) below, both sides
    # 2.22.5, Todd: "the window needs to be a bit wider to get rid of the
    # scroll bar at the bottom." The table rows are exactly TABLE_WIDTH
    # wide, but the scrollLayout below reserves some of its width for a
    # vertical scrollbar track whenever the row list is tall enough to
    # need one — so the space actually available to the rows was a
    # little less than TABLE_WIDTH, triggering a horizontal scrollbar
    # too. This buffer just pads the window past that reserved sliver.
    SCROLLBAR_BUFFER = 24

    window = cmds.window(
        ASSET_MANAGER_WINDOW,
        title="Asset Manager",
        sizeable=False,
        width=TABLE_WIDTH + 2 * OUTER_MARGIN + SCROLLBAR_BUFFER,
    )
    cmds.columnLayout(adjustableColumn=True, columnAlign="left", rowSpacing=6, columnOffset=("both", OUTER_MARGIN))

    cmds.text(label="")  # top spacer

    def on_add_asset(*_args):
        # Leave the Asset Manager window open — Add Asset opens on top of
        # it as a sub-task, not a replacement. Closing it back down
        # refreshes Asset Manager (which also handles closing the old
        # Asset Manager window itself before rebuilding).
        show_asset_manager_add_window(project_path, on_close=show_asset_manager_window)

    # "+ Add Asset" sits directly above the Remove column — its own two
    # columns are now hard-fixed widths too (label gets whatever's left
    # of TABLE_WIDTH after the button), not an adjustable stretch, so it
    # lines up with the table's true right edge by matching pixel math
    # rather than by elastic layout.
    cmds.rowLayout(
        numberOfColumns=2,
        columnWidth2=(TABLE_WIDTH - add_asset_width, add_asset_width),
        columnAlign2=("left", "right"),
    )
    cmds.text(label=f"{len(rows)} reference(s) in scene", align="left")
    cmds.button(label="+ Add Asset", width=add_asset_width, command=on_add_asset)
    cmds.setParent("..")
    cmds.separator(height=10, style="in")

    cmds.rowLayout(
        numberOfColumns=6,
        columnWidth6=column_widths,
        columnAlign6=("left", "left", "left", "left", "right", "left"),
    )
    cmds.text(label="")  # nothing above the checkbox column
    cmds.text(label="Type", font="boldLabelFont", align="left")
    cmds.text(label="Asset Name", font="boldLabelFont", align="left")
    cmds.text(label="Version", font="boldLabelFont", align="left")
    cmds.text(label="Remove", font="boldLabelFont", align="left")
    cmds.text(label="Mode", font="boldLabelFont", align="left")
    cmds.setParent("..")

    cmds.scrollLayout(childResizable=True, height=360)
    cmds.columnLayout(adjustableColumn=True, columnAlign="left")

    row_state = {}  # unique row index -> dict of controls + staged state (ref_node isn't
    # unique enough since imported rows all share ref_node=None)

    if not rows:
        # Same window chrome (header row, scroll area, fixed Remove
        # All/Apply/Close row below) whether or not there's anything
        # loaded — just an empty scroll area instead of a table, so the
        # window doesn't jump between a wide one-button layout and the
        # normal one depending on scene state.
        cmds.text(label="")
        cmds.text(label="No asset references found in this scene.", align="left")

    for idx, row in enumerate(rows):
        task_name = row["task_name"]
        is_import = row["is_import"]
        is_cache_row = row.get("is_cache_row", False)

        cmds.rowLayout(
            numberOfColumns=6,
            columnWidth6=column_widths,
            columnAlign6=("left", "left", "left", "left", "right", "left"),
        )
        checkbox = cmds.checkBox(label="")
        cmds.text(label=ASSET_MANAGER_TASK_LABELS.get(task_name, task_name or "-"), align="left")
        display_name = row["asset_name"] or row["namespace"] or row["filename"]
        cmds.text(label=display_name, align="left")

        version_dropdown = cmds.optionMenu(enable=not is_import)
        version_lookup = {}  # version label -> filename, newest first (insertion order)
        # Cache rows are versioned .abc files (<name>.vNNN.abc), not the
        # .ma/.mb pattern every other row uses — match against the right
        # pattern so the dropdown shows "v001" labels instead of falling
        # back to full filenames.
        version_pattern = CACHE_VERSIONED_FILE_PATTERN if is_cache_row else VERSIONED_FILE_PATTERN
        for filename in row["available_versions"]:
            match = version_pattern.match(filename)
            label = f"v{match.group(2)}" if match else filename
            version_lookup[label] = filename
            cmds.menuItem(label=label, parent=version_dropdown)

        current_label = row["current_version_label"] or row["filename"]
        if current_label not in version_lookup:
            # Loaded version isn't one of the on-disk versions we found
            # (e.g. that file was since deleted) — add it as its own menu
            # item so the dropdown actually reflects what's loaded instead
            # of silently defaulting to the newest available version.
            version_lookup[current_label] = row["filename"]
            cmds.menuItem(label=current_label, parent=version_dropdown)
        cmds.optionMenu(version_dropdown, edit=True, value=current_label)
        version_default_bgc = cmds.optionMenu(version_dropdown, query=True, backgroundColor=True)

        remove_button = cmds.button(label="X", width=26)
        remove_default_bgc = cmds.button(remove_button, query=True, backgroundColor=True)

        # Reference/Import toggle: a live reference row starts on
        # "Reference"; an already-imported row (no reference node left to
        # toggle) is pinned to "Import" and disabled. Switching a live
        # row to "Import" and hitting Apply converts it. Cache rows have
        # neither concept (a merged cache isn't a reference) — show a
        # plain "Merged" label instead of the dropdown.
        if is_cache_row:
            cmds.text(label="Merged", align="left", enable=False)
            mode_dropdown = None
        else:
            mode_dropdown = cmds.optionMenu(enable=not is_import)
            cmds.menuItem(label="Reference", parent=mode_dropdown)
            cmds.menuItem(label="Import", parent=mode_dropdown)
            cmds.optionMenu(mode_dropdown, edit=True, value=("Import" if is_import else "Reference"))

        cmds.setParent("..")

        state = {
            "row": row,
            "is_import": is_import,
            "checkbox": checkbox,
            "version_dropdown": version_dropdown,
            "version_lookup": version_lookup,
            "remove_button": remove_button,
            "mode_dropdown": mode_dropdown,
            "original_label": current_label,
            "pending_remove": False,
            "version_default_bgc": version_default_bgc,
            "remove_default_bgc": remove_default_bgc,
        }
        row_state[idx] = state

        # Green whenever the dropdown has been manually moved off the
        # version that was actually loaded (a staged update, whether from
        # the dropdown itself or Update All); red whenever it's sitting
        # on an outdated version that hasn't been touched yet; default
        # otherwise (untouched and already the newest).
        def make_refresh_version_color(state=state):
            def refresh_version_color(*_args):
                chosen_label = cmds.optionMenu(state["version_dropdown"], query=True, value=True)
                # version_lookup is newest-first insertion order, so its
                # position doubles as a rank: lower index = newer version.
                labels = list(state["version_lookup"].keys())
                chosen_rank = labels.index(chosen_label) if chosen_label in labels else len(labels)
                original_rank = (
                    labels.index(state["original_label"]) if state["original_label"] in labels else len(labels)
                )

                if chosen_rank < original_rank:
                    # Moved to a newer version than what was loaded.
                    cmds.optionMenu(state["version_dropdown"], edit=True, backgroundColor=ASSET_MANAGER_UPDATED_COLOR)
                elif chosen_rank > original_rank:
                    # Rolled back to an older version than what was loaded.
                    cmds.optionMenu(state["version_dropdown"], edit=True, backgroundColor=ASSET_MANAGER_OLD_COLOR)
                elif chosen_rank > 0:
                    # Untouched, but what was loaded isn't the newest available.
                    cmds.optionMenu(state["version_dropdown"], edit=True, backgroundColor=ASSET_MANAGER_OLD_COLOR)
                else:
                    cmds.optionMenu(state["version_dropdown"], edit=True, backgroundColor=state["version_default_bgc"])

            return refresh_version_color

        refresh_version_color = make_refresh_version_color()
        state["refresh_version_color"] = refresh_version_color
        cmds.optionMenu(version_dropdown, edit=True, changeCommand=refresh_version_color)
        refresh_version_color()

        # Removal (the "X") darkens the button rather than relabeling it,
        # and is independent of the (currently unused) checkbox. Stored
        # as a reusable setter so "Remove All" can drive every row the
        # same way a single X click would.
        def make_set_remove(state=state):
            def set_remove(value):
                state["pending_remove"] = value
                if not state["is_import"]:
                    cmds.optionMenu(state["version_dropdown"], edit=True, enable=not value)
                    if state["mode_dropdown"] is not None:  # None for cache rows — no Mode dropdown to toggle
                        cmds.optionMenu(state["mode_dropdown"], edit=True, enable=not value)
                cmds.button(
                    state["remove_button"],
                    edit=True,
                    backgroundColor=(ASSET_MANAGER_OLD_COLOR if value else state["remove_default_bgc"]),
                )

            return set_remove

        set_remove = make_set_remove()
        state["set_remove"] = set_remove

        def on_remove_button(*_args, state=state):
            state["set_remove"](not state["pending_remove"])

        cmds.button(remove_button, edit=True, command=on_remove_button)

    cmds.setParent("..")  # table columnLayout
    cmds.setParent("..")  # scrollLayout

    cmds.separator(height=10, style="in")

    def on_apply(*_args):
        applied = 0
        errors = []

        for state in row_state.values():
            row = state["row"]
            ref_node = row["ref_node"]

            if row.get("is_cache_row"):
                # A cache row has no reference to swap/toggle — just a
                # node with cache data merged onto it (see
                # _attach_cache_to_node / CACHE_ATTR_SHOT). Remove tears
                # that connection down; a version change re-merges onto
                # the newly chosen file the exact same way it was first
                # attached, replacing the old AlembicNode rather than
                # stacking a second one on top of it.
                cache_node = row["cache_obj_node"]
                if state["pending_remove"]:
                    try:
                        for old_node in _find_connected_alembic_nodes(cache_node):
                            cmds.delete(old_node)
                        for attr in (CACHE_ATTR_SHOT, CACHE_ATTR_NAME):
                            if cmds.attributeQuery(attr, node=cache_node, exists=True):
                                cmds.deleteAttr(f"{cache_node}.{attr}")
                        applied += 1
                    except Exception as e:
                        errors.append(f"{row['asset_name']}: could not remove cache ({e})")
                    continue

                chosen_label = cmds.optionMenu(state["version_dropdown"], query=True, value=True)
                if chosen_label == state["original_label"]:
                    continue  # nothing staged for this row

                new_filename = state["version_lookup"].get(chosen_label)
                if not new_filename:
                    errors.append(f"{row['asset_name']}: could not resolve cache version {chosen_label}")
                    continue

                cache_dir = get_shot_cache_dir(project_path, row["cache_shot_name"])
                new_path = os.path.join(cache_dir, new_filename)
                try:
                    # 2.31.12: use the resolved (possibly re-parented)
                    # node, same fix as AssetManagerPanel._do_update's
                    # version-swap branch — see _attach_cache_to_node's
                    # 2.31.12 note.
                    resolved_cache_node = _attach_cache_to_node(new_path, cache_node)
                    _tag_cache_attachment(
                        resolved_cache_node, row["cache_shot_name"], row["cache_name"], filename=new_filename
                    )
                    applied += 1
                except Exception as e:
                    errors.append(f"{row['asset_name']}: could not swap cache version ({e})")
                continue

            if row["is_import"]:
                # Already imported (no reference node left) — the only
                # thing left to stage is removing it outright.
                if state["pending_remove"]:
                    try:
                        cmds.namespace(removeNamespace=row["namespace"], deleteNamespaceContent=True)
                        applied += 1
                    except Exception as e:
                        errors.append(f"{row['namespace']}: could not remove ({e})")
                continue

            if state["pending_remove"]:
                try:
                    cmds.file(referenceNode=ref_node, removeReference=True)
                    applied += 1
                except Exception as e:
                    errors.append(f"{row['filename']}: could not remove ({e})")
                continue

            mode = cmds.optionMenu(state["mode_dropdown"], query=True, value=True)
            if mode == "Import":
                try:
                    # Bakes the reference into the scene as regular nodes
                    # (still under the same namespace, so Asset Manager
                    # keeps tracking it as an imported row afterward).
                    cmds.file(importReference=True, referenceNode=ref_node)
                    applied += 1
                except Exception as e:
                    errors.append(f"{row['filename']}: could not import reference ({e})")
                continue

            chosen_label = cmds.optionMenu(state["version_dropdown"], query=True, value=True)
            if chosen_label == state["original_label"]:
                continue  # nothing staged for this row

            new_filename = state["version_lookup"].get(chosen_label)
            if not new_filename or not row["asset_name"] or not row["task_name"]:
                errors.append(f"{row['filename']}: could not resolve version {chosen_label}")
                continue

            asset_dir = find_asset_folder(project_path, row["asset_name"])
            if not asset_dir:
                errors.append(f"{row['filename']}: asset folder not found")
                continue

            new_path = os.path.join(asset_task_source_dir(asset_dir, row["task_name"]), new_filename)
            try:
                # cmds.file has no "replaceReference" flag — swapping an
                # existing reference to a different file is done by
                # passing the new path together with loadReference set to
                # that reference node.
                cmds.file(new_path, loadReference=ref_node)

                # loadReference doesn't rename the reference's namespace
                # to match the new file on its own, so the namespace was
                # staying stuck on whatever version it was first
                # referenced under. Rename it to match the new version
                # explicitly.
                try:
                    old_namespace = cmds.referenceQuery(ref_node, namespace=True).lstrip(":")
                    new_namespace = namespace_for_versioned_file(new_filename)
                    if old_namespace and old_namespace != new_namespace:
                        cmds.namespace(rename=(old_namespace, new_namespace))
                except Exception as e:
                    errors.append(f"{row['filename']}: swapped version but could not rename namespace ({e})")

                applied += 1
            except Exception as e:
                errors.append(f"{row['filename']}: could not swap version ({e})")

        if errors:
            cmds.confirmDialog(
                title="Asset Manager",
                message="Applied {} change(s).\n\nSome changes could not be applied:\n{}".format(
                    applied, "\n".join(errors)
                ),
                button=["OK"],
            )
        elif applied:
            print(f"Asset Manager: applied {applied} change(s).")

        # Apply doesn't close the window — refresh it in place instead so
        # the table reflects what's actually loaded now (rows that got
        # removed drop out, swapped versions show as the new "current").
        if applied:
            cmds.deleteUI(window)
            show_asset_manager_window()

    def on_remove_all(*_args):
        # Same as clicking "X" on every row — still just staged until Apply.
        for state in row_state.values():
            state["set_remove"](True)

    # "Remove All" on the left; Apply and Close sit snug next to each
    # other at the bottom right. The middle spacer's width is now a hard
    # fixed number (TABLE_WIDTH minus the three buttons), computed the
    # same way as the "+Add Asset" row above, instead of an adjustable
    # column that stretches/shrinks with the window.
    cmds.rowLayout(
        numberOfColumns=4,
        columnWidth4=(90, TABLE_WIDTH - 90 - 90 - 90, 90, 90),
        columnAlign4=("left", "left", "right", "right"),
    )
    cmds.button(label="Remove All", width=90, command=on_remove_all, enable=bool(rows))
    cmds.text(label="")
    cmds.button(label="Apply", width=90, command=on_apply, enable=bool(rows))
    cmds.button(label="Close", width=90, command=lambda *a: cmds.deleteUI(window))
    cmds.setParent("..")

    cmds.text(label="")  # bottom spacer

    cmds.showWindow(window)


# ------------------------------------------------------------------
# Asset Manager v2 — PySide dock panel (2.23.0)
# ------------------------------------------------------------------
# Overhaul of the Asset Manager interface based on a Claude Design mockup
# Todd provided (design_handoff_maya_asset_manager/ — "Scene Manager -
# Maya Panel.dc.html" + its README). Ask: "i want to overhaul the
# interface for the asset manager based on something built in claude
# design" then, once the mockup was reviewed and a rollback snapshot of
# the file was made (pipeline_menu_PRE_ASSET_MANAGER_OVERHAUL_v2.22.7.py):
# "ok.. build the new asset manager."
#
# This is a NEW panel, not a reskin of show_asset_manager_window above —
# the mockup's own README calls for a DOCKED PySide/PyQt panel
# (QDockWidget via Maya's mayaMixin), not a cmds.window popup, so the two
# use fundamentally different toolkits. show_asset_manager_window is left
# fully intact and still callable — the ASSET_MANAGER_ROLLBACK note below
# is how to get back to it if this overhaul needs undoing; see also the
# standalone rollback file for the whole pre-overhaul pipeline_menu.py.
#
# ASSET_MANAGER_ROLLBACK: to revert to the old cmds-based popup, change
# the "Asset Manager" menu item's command back to
# `lambda *a: show_asset_manager_window()` (it currently opens
# show_asset_manager_panel() instead) — show_asset_manager_window()
# itself was not touched by this overhaul and still works standalone.
#
# Deliberate deviations from the literal mockup, and why:
#  1. Cache rows still require a one-step "Pick Shade Asset" popup
#     (show_cache_shade_picker_window) instead of a modal-free "+" like
#     real assets get. The mockup's "no modal" spec doesn't model the
#     real constraint that a cache can only be merged (AbcImport
#     connect=) onto an EXISTING Shade asset's already-referenced "OBJ"
#     node (see the 2.21.3/2.22.0 notes above) — there's no way to know
#     which Shade asset a cache should attach to without asking. Cache
#     adds also commit to the scene IMMEDIATELY on that popup's Import
#     (same as the old Add Asset flow), rather than staging for the
#     panel's own "Update" button — deferring it would mean re-asking
#     "which Shade asset" a second time at commit, which is worse UX.
#  2. Asset browse rows are one row per (asset, task) rather than one row
#     per asset — e.g. an asset published for both Model and Rig shows as
#     two separate browse rows ("assetName" / Model Asset badge, and
#     "assetName" / Rig Asset badge). The mockup's fixture data only ever
#     shows one kind per asset; the real pipeline lets one asset have up
#     to 4 published tasks (model/rig/lookdev/fx) simultaneously, each
#     independently referenceable and independently versioned, so
#     collapsing to one row per asset would hide that.
#  3. An "FX Asset" badge color (#e0995a bg / #331d0f fg) was added,
#     following the same palette family as the mockup's other three type
#     badges — the mockup's fixture data never includes an fx example,
#     but the real pipeline does have an fx task.
#  4. Browse row subtitles show "vN available" instead of an artist name
#     — the pipeline doesn't track per-file artist metadata anywhere, so
#     there's nothing real to show there; version count is the closest
#     genuinely-available substitute.
#  5. "Anim Cache" as a top-level Assets-tab entry (as in the mockup's
#     fixture data, e.g. "cargo_crate") doesn't exist for real — caches
#     live under shots/<shot>/anim/output/cache/, not assets/<type>/, so
#     they only ever appear under the Shots tab / shot drill-in, same as
#     every other cache-related flow already built in this file.

try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from shiboken6 import wrapInstance as _am_wrap_instance
    _AM_QT_BINDING = "PySide6"
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets
    from shiboken2 import wrapInstance as _am_wrap_instance
    _AM_QT_BINDING = "PySide2"

try:
    from maya.app.general.mayaMixin import MayaQWidgetDockableMixin
except ImportError:
    # Lets this file still import/py_compile outside Maya (this repo's
    # dev/test environment has no maya.app module at all) — the panel
    # simply can't be opened there, same as every other cmds-dependent
    # function in this file.
    class MayaQWidgetDockableMixin(object):  # noqa: N801 - matches Maya's name
        pass

try:
    # 2.26.0 — only needed to parent the (non-dockable) Export/Import
    # Pipeline panels to Maya's main window so they don't get lost behind
    # the viewport; see _pipeline_panel_show. Same import-guard pattern as
    # MayaQWidgetDockableMixin above.
    import maya.OpenMayaUI as omui
except ImportError:
    omui = None


ASSET_MANAGER_PANEL_OBJECT_NAME = "assetManagerPanel"
ASSET_MANAGER_PANEL_TITLE = "Asset Manager"

# 2.24.0 — Import Caches panel object name, sharing _am_stylesheet() and
# AM_TOKENS with the Asset Manager panel (see ImportCachesPanel below).
IMPORT_CACHES_PANEL_OBJECT_NAME = "importCachesPanel"
IMPORT_CACHES_PANEL_TITLE = "Import Caches"

# 2.26.0 — Export/Import Pipeline panels, sharing AM_TOKENS/_am_stylesheet
# with Asset Manager (see the "Export / Import Pipeline" module comment
# near build_asset_task_structure's callers). Plain QWidget top-levels,
# NOT MayaQWidgetDockableMixin — Todd: "i dont actually want either of
# them pyside dockable."
EXPORT_PIPELINE_PANEL_OBJECT_NAME = "exportPipelinePanel"
EXPORT_PIPELINE_PANEL_TITLE = "Export Pipeline"
IMPORT_PIPELINE_PANEL_OBJECT_NAME = "importPipelinePanel"
IMPORT_PIPELINE_PANEL_TITLE = "Import Pipeline"

# Design tokens straight from design_handoff_maya_asset_manager/README.md
# ("Design Tokens" section) and cross-checked against the .dc.html mockup
# — kept in one dict so the whole panel's look traces back to one place.
AM_TOKENS = {
    "bg_panel": "#2b2b2b",
    "bg_header": "#333333",
    "bg_section_header": "#2f2f2f",
    "bg_group_header": "#282828",
    "border": "#1e1e1e",
    "text_primary": "#d6d6d6",
    "text_primary_alt": "#dedede",
    "text_muted": "#7a7a7a",
    "text_muted_alt": "#8a8a8a",
    "text_active": "#eaeaea",
    "text_white": "#ffffff",
    "green": "#5fae5f",
    "green_dark": "#4d8a4d",
    "green_light": "#8fd18f",
    "blue_bg": "#3d6b8a",
    "blue_bar_bg": "#31414a",
    "blue_row_bg": "#33424a",
    "blue_text": "#cfe3ec",
    "red_bg": "#5a3232",
    "red_status_bg": "#e05252",
    "red_status_text": "#3a1414",
    "red_text": "#f0c9c9",
    "red_outdated_text": "#e28a8a",
    "red_remove_icon": "#c98f8f",
    "button_neutral_bg": "#454545",
    # 2.23.4 — hover/pressed variants for the QSS button states added
    # this pass. One shade lighter than each button's resting color;
    # pressed is a shade darker than resting (a quick "being pushed"
    # dip rather than just repeating the hover color).
    "button_neutral_hover": "#565656",
    "button_neutral_pressed": "#3a3a3a",
    "green_dark_hover": "#5c985c",
    "green_dark_pressed": "#3f723f",
    "red_bg_hover": "#6b3c3c",
    "nav_hover_bg": "#3a3a3a",
    "blue_bg_hover": "#48769a",
    # 2.23.2 — Todd: "id like a little more separation between the three
    # columns.. by a vertical line maybe.. also color could help.. maybe
    # the left can be the lighter gray and the two other windows can be
    # dark." Nav rail gets the lighter bg; Browse list + In Scene both
    # get the darker bg; a visibly-thicker/lighter border sits between
    # every column (vs. the subtle #1e1e1e hairline used for in-list row
    # dividers elsewhere, which stays as-is).
    "bg_nav_rail": "#454545",
    "bg_dark_column": "#242424",
    "border_column": "#525252",
    # 2.26.0 — Export/Import Pipeline's yellow "partial match" row color
    # (Custom Import diff view). Same family as red_bg/red_text above,
    # just the yellow half of that red/yellow convention.
    "yellow_bg": "#5a5222",
    "yellow_text": "#f0e6a3",
}

# Type badges — model/rig/lookdev colors are straight from the handoff;
# "fx" is the one addition beyond the literal mockup (see deviation #3
# above). lookdev's badge label stays "Lookdev Asset" (matching the
# mockup's own copy) even though this file elsewhere labels the lookdev
# task "Shade" (ASSET_MANAGER_TASK_LABELS) — deliberately kept as the
# mockup's exact wording here since Todd said to build the design as
# handed off; if he wants "Shade" instead, that's a one-line follow-up.
AM_TYPE_BADGES = {
    "model": {"label": "Model Asset", "bg": "#5a8fc7", "fg": "#122333"},
    "rig": {"label": "Rig Asset", "bg": "#a78bd1", "fg": "#241c33"},
    "lookdev": {"label": "Lookdev Asset", "bg": "#d1a34a", "fg": "#332510"},
    "fx": {"label": "FX Asset", "bg": "#e0995a", "fg": "#331d0f"},
}

# 2.24.4: display names for the Assets tab's task-category drill-down
# (see _panel_asset_task_category_items) — same task keys as
# ASSET_TASK_SUFFIXES, just the short form used for a category header/
# nav-tab label rather than a per-row badge.
ASSET_MANAGER_CATEGORY_LABELS = {
    "model": "Model",
    "rig": "Rig",
    "lookdev": "Lookdev",
    "fx": "FX",
}


def _am_stylesheet():
    """
    One QSS blob for the whole panel, built from AM_TOKENS — every color
    in here should trace back to that dict rather than a hardcoded hex,
    same principle as the mockup's own single "Design Tokens" section.
    """
    t = AM_TOKENS
    return f"""
        QWidget#{ASSET_MANAGER_PANEL_OBJECT_NAME}, QWidget#{IMPORT_CACHES_PANEL_OBJECT_NAME},
        QWidget#{EXPORT_PIPELINE_PANEL_OBJECT_NAME}, QWidget#{IMPORT_PIPELINE_PANEL_OBJECT_NAME} {{
            background: {t['bg_panel']};
            color: {t['text_primary']};
            font-family: "Inter", "Segoe UI", sans-serif;
            font-size: 11px;
        }}
        QWidget#amNavRail {{
            background: {t['bg_nav_rail']};
            border-right: 2px solid {t['border_column']};
        }}
        QWidget#amBrowseList {{
            background: {t['bg_dark_column']};
            border-right: 2px solid {t['border_column']};
        }}
        QWidget#amSceneCol {{
            background: {t['bg_dark_column']};
        }}
        QLabel[class="amSectionHeader"] {{
            background: {t['bg_section_header']};
            color: {t['text_muted']};
            font-size: 9.5px;
            font-weight: 600;
            padding: 4px 10px;
            border-bottom: 1px solid {t['border']};
        }}
        QLabel[class="amGroupHeader"] {{
            background: {t['bg_group_header']};
            color: {t['text_muted_alt']};
            font-size: 9.5px;
            font-weight: 700;
            padding: 5px 10px 2px 10px;
        }}
        QLabel[class="amStateHeader"] {{
            color: {t['text_active']};
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 0.3px;
            padding: 8px 10px 4px 10px;
        }}
        QPushButton[class="amNavTab"] {{
            text-align: left;
            padding: 9px 10px;
            border: none;
            border-left: 2px solid transparent;
            border-radius: 0px;
            color: #a0a0a0;
            background: transparent;
            font-size: 11px;
        }}
        QPushButton[class="amNavTab"]:hover {{
            background: {t['nav_hover_bg']};
            color: {t['text_primary_alt']};
        }}
        QPushButton[class="amNavTabActive"] {{
            text-align: left;
            padding: 9px 10px;
            border: none;
            border-left: 2px solid {t['green']};
            border-radius: 0px;
            color: {t['text_white']};
            background: {t['blue_bg']};
            font-weight: 600;
            font-size: 11px;
        }}
        QPushButton[class="amNavTabActive"]:hover {{
            background: {t['blue_bg_hover']};
        }}
        QPushButton[class="amAddBtn"] {{
            background: {t['button_neutral_bg']};
            color: {t['green_light']};
            border: none;
            border-radius: 2px;
            font-weight: 700;
        }}
        QPushButton[class="amAddBtn"]:hover {{
            background: {t['button_neutral_hover']};
        }}
        QPushButton[class="amAddBtn"]:pressed {{
            background: {t['button_neutral_pressed']};
        }}
        QPushButton[class="amFooterUpdate"] {{
            background: {t['green_dark']};
            color: {t['text_white']};
            border: 1px solid {t['border']};
            border-radius: 2px;
            padding: 6px 16px;
            font-weight: 600;
            font-size: 11px;
        }}
        QPushButton[class="amFooterUpdate"]:hover {{
            background: {t['green_dark_hover']};
        }}
        QPushButton[class="amFooterUpdate"]:pressed {{
            background: {t['green_dark_pressed']};
        }}
        QPushButton[class="amFooterCancel"] {{
            background: {t['button_neutral_bg']};
            color: {t['text_primary_alt']};
            border: 1px solid {t['border']};
            border-radius: 2px;
            padding: 6px 14px;
            font-size: 11px;
        }}
        QPushButton[class="amFooterCancel"]:hover {{
            background: {t['button_neutral_hover']};
        }}
        QPushButton[class="amFooterCancel"]:pressed {{
            background: {t['button_neutral_pressed']};
        }}
        QToolButton[class="amRemoveBtn"] {{
            color: {t['red_remove_icon']};
            border: none;
            border-radius: 2px;
            font-size: 12px;
        }}
        QToolButton[class="amRemoveBtn"]:hover {{
            background: {t['red_bg']};
            color: {t['red_text']};
        }}
        QToolButton[class="amRemoveBtnMarked"] {{
            background: {t['red_status_bg']};
            color: {t['text_white']};
            border: none;
            border-radius: 2px;
            font-size: 11px;
            padding: 1px 4px;
        }}
        QToolButton[class="amRemoveBtnMarked"]:hover {{
            background: {t['red_bg_hover']};
        }}
        QComboBox[class="amVersionCombo"] {{
            font-family: "JetBrains Mono", monospace;
            font-size: 10px;
            background: #3a3a3a;
            color: {t['text_primary_alt']};
            border: 1px solid {t['border']};
            border-radius: 2px;
            padding: 2px 3px;
        }}
        QComboBox[class="amVersionCombo"]:hover {{
            border: 1px solid {t['border_column']};
        }}
        QComboBox[class="amImportModeCombo"] {{
            font-size: 9.5px;
            background: #3a3a3a;
            color: {t['text_primary_alt']};
            border: 1px solid {t['border']};
            border-radius: 2px;
            padding: 2px 4px;
        }}
        QComboBox[class="amImportModeCombo"]:hover {{
            border: 1px solid {t['border_column']};
        }}
        QComboBox[class="amImportModeCombo"]:disabled {{
            color: {t['text_muted']};
        }}
        QFrame#amRemovalBar {{
            background: {t['red_bg']};
            border-bottom: 1px solid {t['border']};
        }}
        QFrame#amSceneRow {{
            border-bottom: 1px solid #232323;
        }}
        QFrame#amSceneRowMarked {{
            background: #3a2323;
            border-bottom: 1px solid #232323;
        }}

        /* 2.24.0 — Import Caches panel, sharing this same stylesheet/
           tokens (see ImportCachesPanel) rather than a separate QSS
           blob, so it stays visually in lock-step with the Asset
           Manager panel going forward. */
        QFrame#icRow {{
            border-bottom: 1px solid #232323;
        }}
        QFrame#icHeaderRow {{
            background: {t['bg_section_header']};
            border-bottom: 1px solid {t['border']};
        }}
        QComboBox[class="amShadeCombo"] {{
            font-size: 10.5px;
            background: #3a3a3a;
            color: {t['text_primary_alt']};
            border: 1px solid {t['border']};
            border-radius: 2px;
            padding: 2px 4px;
        }}
        QComboBox[class="amShadeCombo"]:hover {{
            border: 1px solid {t['border_column']};
        }}
        QCheckBox[class="icRowCheck"]::indicator {{
            width: 13px;
            height: 13px;
            border: 1px solid {t['border_column']};
            border-radius: 2px;
            background: #3a3a3a;
        }}
        QCheckBox[class="icRowCheck"]::indicator:checked {{
            background: {t['green_dark']};
            border: 1px solid {t['green_dark']};
        }}
        QCheckBox[class="icRowCheck"]::indicator:hover {{
            border: 1px solid {t['border_column']};
        }}
    """


# 2.28.0: Todd — "asset manager import as options" — the old dead
# cmds-based Add Asset window had a Load/Import/Reference dropdown
# (2.13.25) that never made it into the PySide AssetManagerPanel
# rewrite, which has hardcoded every "+" add to Reference ever since.
# Restored as a per-row dropdown, and (per Todd, 2026-08-27) extended to
# already-in-scene rows too so an asset's mode can be changed at any
# time, not just at add time. Naming deliberately inverted from the old
# 2.13.25 dropdown (there "Load" was untracked/no-namespace and "Import"
# was namespaced/trackable) — Todd: "I inverted the old terminology
# because it tracks more closely to Maya's terminology."
#
#   import_untracked ("Import")       -> cmds.file(i=True, namespace=":", ...)
#                                         no namespace, not trackable/discoverable
#                                         again once the scene is refreshed.
#   import_tracked    ("Load [tracked]") -> cmds.file(i=True, namespace=<versioned>, ...)
#                                         keeps the "<asset>_<task>_vNNN" namespace
#                                         convention, so _asset_manager_collect_imported_rows
#                                         still finds/tracks it on refresh.
#   reference          ("Reference")   -> cmds.file(reference=True, ...) — unchanged
#                                         default behavior from before this feature.
#
# Maya can bake a Reference into an Import (importReference) but can't
# reverse that, so "Reference" is disabled on the dropdown for any row
# that's already an import (tracked or untracked) — see
# _AssetManagerSceneRow and the mode-conversion branch in
# AssetManagerPanel._do_update. Cache rows don't get this dropdown at
# all (caches attach to a node, they aren't referenced/imported files).
ASSET_MANAGER_IMPORT_MODE_ORDER = ("import_untracked", "import_tracked", "reference")
ASSET_MANAGER_IMPORT_MODE_LABELS = {
    "import_untracked": "Import",
    "import_tracked": "Load [tracked]",
    "reference": "Reference",
}


def _am_status_pill(outdated):
    t = AM_TOKENS
    label = QtWidgets.QLabel("OLD" if outdated else "OK")
    bg = t["red_status_bg"] if outdated else t["green_light"]
    fg = t["red_status_text"] if outdated else "#1c3620"
    label.setStyleSheet(
        f"background:{bg}; color:{fg}; font-size:8.5px; font-weight:700; "
        f"border-radius:2px; padding:1px 5px;"
    )
    label.setFixedHeight(14)
    return label


# ---------------- Data collection for the browse lists ----------------

def _panel_asset_type_items(project_path):
    """
    2.27.0: Assets tab's new top-level browse list — one entry per
    asset-category Type that actually exists under assets/ (char/environ/
    prop plus any custom types Todd has created), each with a count of
    how many assets it contains. Added because Type was previously
    skipped entirely in the Asset Manager panel: a custom-type asset was
    reachable (task categories/asset lists scanned every type folder
    under the hood), but there was no way to see or filter by which type
    an asset belonged to. Clicking a type drills into
    _panel_asset_task_category_items(project_path, type_name).
    """
    items = []
    for type_name in list_asset_category_types(project_path):
        count = len(list_all_assets(project_path, type_name=type_name))
        items.append(
            {
                "id": type_name,
                "name": type_name.capitalize(),
                "sub": f"{count} asset{'s' if count != 1 else ''}",
                "type_name": type_name,
            }
        )
    return items


def _panel_asset_task_category_items(project_path, type_name=None):
    """
    2.24.4: Todd — "if asset is clicked.. the second column shows model /
    rig / lookdev.. then drill down into model or rig or lookdev to get
    to the specific asset." One entry per task in ASSET_TASK_SUFFIXES,
    with a count of how many assets currently have at least one
    published/available version for that task — the Assets tab's
    top-level browse list, replacing the old flat (asset, task) list
    (still used, just one level deeper — see _on_open_asset_task).

    2.27.0: type_name narrows the count to just that one asset type — now
    that Type is its own drill-down level above this one (see
    _panel_asset_type_items), this is always called with a type_name in
    practice, but the default (None, every type) is kept for
    backward-compatibility with any other caller.
    """
    items = []
    for task_name in ASSET_TASK_SUFFIXES:
        count = len(list_assets_with_task(project_path, task_name, type_name=type_name))
        items.append(
            {
                "id": task_name,
                "name": ASSET_MANAGER_CATEGORY_LABELS.get(task_name, task_name),
                "sub": f"{count} asset{'s' if count != 1 else ''}",
                "task_name": task_name,
            }
        )
    return items


def _panel_asset_browse_items(project_path, task_name=None, type_name=None):
    """
    One entry per (asset, task) that has at least one published/available
    version — see deviation #2 above for why this isn't one row per
    asset. Sorted by asset name, then by ASSET_TASK_SUFFIXES order so an
    asset's multiple task rows sit together and in a stable order.

    2.24.4: task_name narrows this to just that one task, for the Assets
    tab's category drill-down (_panel_asset_task_category_items) — the
    default (None) still returns every task's rows, unused elsewhere
    today but left in place rather than assumed dead.

    2.27.0: type_name further narrows to just that one asset type (see
    _panel_asset_type_items) — carried through to get_asset_task_versions
    so a version lookup resolves the exact assets/<type>/<name> folder
    instead of find_asset_folder's first-match-wins scan, which matters
    if two different types ever have same-named assets.
    """
    items = []
    for task in (ASSET_TASK_SUFFIXES if task_name is None else (task_name,)):
        badge = AM_TYPE_BADGES[task]
        for asset_name in list_assets_with_task(project_path, task, type_name=type_name):
            versions = get_asset_task_versions(project_path, asset_name, task, type_name=type_name)
            if not versions:
                continue
            items.append(
                {
                    "id": f"{asset_name}::{task}",
                    "name": asset_name,
                    "sub": f"v{len(versions)} available" if len(versions) != 1 else "1 version",
                    "kind_label": badge["label"],
                    "kind_bg": badge["bg"],
                    "kind_fg": badge["fg"],
                    "asset_name": asset_name,
                    "task_name": task,
                    "asset_type": type_name,
                    "available_versions": versions,  # newest first
                }
            )
    items.sort(key=lambda e: (e["name"], ASSET_TASK_SUFFIXES.index(e["task_name"])))
    return items


def _panel_shot_browse_items(project_path):
    """One entry per shot, subtitle = how many distinct cache names it has."""
    items = []
    for shot_name in list_existing_shots(project_path):
        cache_names = get_shot_cache_names(project_path, shot_name)
        items.append(
            {
                "id": shot_name,
                "name": shot_name,
                "sub": f"{len(cache_names)} cache{'s' if len(cache_names) != 1 else ''}",
                "shot_name": shot_name,
            }
        )
    return items


def _panel_shot_cache_items(project_path, shot_name):
    """One entry per cache name for a drilled-into shot."""
    items = []
    for cache_name in get_shot_cache_names(project_path, shot_name):
        versions = get_shot_cache_versions(project_path, shot_name, cache_name)
        if not versions:
            continue
        match = CACHE_VERSIONED_FILE_PATTERN.match(versions[0])
        latest_label = f"v{match.group(2)}" if match else versions[0]
        items.append(
            {
                "id": f"{shot_name}::{cache_name}",
                "name": cache_name,
                "sub": f"latest {latest_label}",
                "shot_name": shot_name,
                "cache_name": cache_name,
                "available_versions": versions,
            }
        )
    return items


def _panel_version_labels(available_versions, is_cache):
    pattern = CACHE_VERSIONED_FILE_PATTERN if is_cache else VERSIONED_FILE_PATTERN
    labels = []
    for filename in available_versions:
        match = pattern.match(filename)
        labels.append(f"v{match.group(2)}" if match else filename)
    return labels


def _panel_seed_scene_items(project_path):
    """
    Build the panel's "In Scene" state from what's actually loaded, by
    reusing _asset_manager_collect_rows — the exact same discovery logic
    the old cmds-based Asset Manager already relies on (live references,
    switched-to-Import namespaces, and tagged cache attachments), so this
    panel doesn't reimplement scene discovery from scratch.
    """
    items = {}
    # 2.24.5: namespace -> asset item id, built up as real-asset rows are
    # seeded, so cache rows (processed in the same pass) can link back to
    # the Shade asset they're actually merged onto — see the linking pass
    # at the end of this function.
    namespace_to_asset_item_id = {}
    for row in _asset_manager_collect_rows(project_path):
        is_cache = row.get("is_cache_row", False)
        version_labels = _panel_version_labels(row["available_versions"], is_cache)
        try:
            current_index = version_labels.index(row["current_version_label"])
        except (ValueError, TypeError):
            current_index = 0

        if is_cache:
            # 2.24.3: same fix as the real-asset branch below — fold the
            # node the cache is actually attached to into the id, since
            # 2.24.2 let the same cache be staged/attached onto more than
            # one Shade asset instance. Without this, two attachments of
            # the same shot+cache name collapsed into one row on refresh.
            item_id = f'{row["cache_shot_name"]}::{row["cache_name"]}::{row["cache_obj_node"] or ""}'
            items[item_id] = {
                "id": item_id,
                "label": f'{row["cache_shot_name"]} — {row["cache_name"]}',
                "category": "Shots",
                "is_cache": True,
                "cache_shot_name": row["cache_shot_name"],
                "cache_name": row["cache_name"],
                "cache_obj_node": row["cache_obj_node"],
                "available_versions": row["available_versions"],
                "version_labels": version_labels,
                "current_index": current_index,
                "original_index": current_index,
                "pending_state": "existing",
                "is_import": False,
                "attached_namespace": row.get("attached_namespace"),
                "attached_asset_label": row.get("attached_asset_label"),
                "attached_asset_item_id": None,  # filled in by the linking pass below
            }
        else:
            asset_name = row["asset_name"] or row["namespace"] or row["filename"]
            task_label = ASSET_MANAGER_TASK_LABELS.get(row["task_name"], row["task_name"] or "-")
            # 2.24.3: Todd — "its not keeping a proper count of all the
            # assets ive brought into the scene." Root cause: this id used
            # to be just f"{asset_name}::{task_name}" with no namespace/
            # ref_node in it — fine when only one reference of a given
            # asset+task could ever exist, but 2.24.1 added multi-add
            # (multiple independently-namespaced references of the SAME
            # asset+task). Re-seeding from the real scene built one dict
            # entry per row, but every extra instance of the same
            # asset+task shared this same key, so each one just overwrote
            # the last in `items` — the scene had N references, the panel
            # showed 1. Namespace is guaranteed unique per reference (Maya
            # enforces it, and _unique_reference_namespace guarantees a
            # free one at Update time), so folding it into the id keeps
            # every real instance as its own row.
            item_id = (
                f'{row["asset_name"]}::{row["task_name"]}::{row["namespace"] or row["ref_node"] or ""}'
                if row["asset_name"] and row["task_name"]
                else f'ns::{row["namespace"] or row["filename"]}'
            )
            items[item_id] = {
                "id": item_id,
                "label": f"{asset_name} — {task_label}",
                "category": "Assets",
                "is_cache": False,
                "ref_node": row["ref_node"],
                "namespace": row["namespace"],
                "asset_name": row["asset_name"],
                "task_name": row["task_name"],
                "available_versions": row["available_versions"],
                "version_labels": version_labels,
                "current_index": current_index,
                "original_index": current_index,
                "pending_state": "existing",
                "is_import": row["is_import"],
                # 2.28.0: seed the current Import As state from real scene
                # discovery — "import_tracked" if _asset_manager_collect_rows
                # already found it via the namespace-convention scan
                # (is_import=True), otherwise it's a live reference. An
                # untracked import is, by definition, undiscoverable here.
                "import_mode": "import_tracked" if row["is_import"] else "reference",
                "original_import_mode": "import_tracked" if row["is_import"] else "reference",
                "attached_cache_item_ids": [],  # filled in by the linking pass below
            }
            if row["namespace"]:
                namespace_to_asset_item_id[row["namespace"]] = item_id

    # 2.24.5: link every cache row back to the Shade asset row it's
    # actually merged onto (by namespace) — Todd: "show which shade file
    # is attached to which cache.. just to show they are linked" plus
    # cascading removal so removing a Shade asset also removes any
    # cache(s) merged onto it, instead of leaving them dangling. See
    # AssetManagerPanel._on_row_mark_toggle for the removal-cascade side
    # of this.
    for item in items.values():
        if not item.get("is_cache"):
            continue
        asset_item_id = namespace_to_asset_item_id.get(item.get("attached_namespace"))
        if asset_item_id:
            item["attached_asset_item_id"] = asset_item_id
            items[asset_item_id]["attached_cache_item_ids"].append(item["id"])

    return items


class _AssetManagerBrowseRow(QtWidgets.QFrame):
    """One row in the Browse list — an asset/task, a shot, or a cache."""

    clicked = QtCore.Signal()
    add_clicked = QtCore.Signal()

    def __init__(self, name, sub, kind=None, has_add=False, has_chevron=False, parent=None):
        super().__init__(parent)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(8, 7, 8, 7)
        layout.setSpacing(7)

        text_col = QtWidgets.QVBoxLayout()
        text_col.setSpacing(2)
        name_row = QtWidgets.QHBoxLayout()
        name_row.setSpacing(6)
        name_label = QtWidgets.QLabel(name)
        name_label.setStyleSheet(f"color:{AM_TOKENS['text_primary']}; font-size:11px; font-weight:500;")
        name_row.addWidget(name_label)
        if kind:
            badge = QtWidgets.QLabel(kind["label"])
            badge.setStyleSheet(
                f"background:{kind['bg']}; color:{kind['fg']}; font-size:8px; "
                f"font-weight:700; border-radius:2px; padding:1px 5px;"
            )
            name_row.addWidget(badge)
        name_row.addStretch(1)
        text_col.addLayout(name_row)
        sub_label = QtWidgets.QLabel(sub)
        sub_label.setStyleSheet(f"color:{AM_TOKENS['text_muted']}; font-size:9.5px;")
        text_col.addWidget(sub_label)
        layout.addLayout(text_col, 1)

        if has_add:
            # 2.24.1: Todd — "it doesnt need to change to a check mark...
            # its not meant to verify the existence in the scene... thats
            # what the list on the right is." The "+" always stays a "+"
            # regardless of whether this asset/task is already staged or
            # in the scene — clicking it queues another add (see
            # AssetManagerPanel._on_add_asset), it never blocks a repeat
            # click, so an asset can be added more than once if that's
            # what the shot needs. Whether something's actually in the
            # scene is entirely the right-hand list's job now.
            add_btn = QtWidgets.QPushButton("+")
            add_btn.setProperty("class", "amAddBtn")
            add_btn.setCursor(QtCore.Qt.PointingHandCursor)
            add_btn.setFixedSize(16, 16)
            add_btn.clicked.connect(self.add_clicked.emit)
            layout.addWidget(add_btn)
        elif has_chevron:
            chevron = QtWidgets.QLabel("›")
            chevron.setStyleSheet(f"color:{AM_TOKENS['text_muted']}; font-size:11px;")
            layout.addWidget(chevron)

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)


class _AssetManagerSceneRow(QtWidgets.QFrame):
    """
    One row in the In Scene table.

    2.23.2: dropped the per-row checkbox (Todd: "lose the check box").
    The ✕ button no longer removes anything immediately — clicking it
    just marks the row for removal (visually distinct: dark-red row
    background, struck-through label, ✕ becomes a filled red pill) and
    clicking it again un-marks it. Nothing actually happens in the scene
    until the footer's Update button is clicked — same staged-changes
    pattern the rest of this panel already uses for adds/version swaps.
    """

    version_changed = QtCore.Signal(int)
    remove_clicked = QtCore.Signal()
    import_mode_changed = QtCore.Signal(str)

    def __init__(self, item, marked, parent=None):
        super().__init__(parent)
        self.setObjectName("amSceneRowMarked" if marked else "amSceneRow")
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(6)

        outdated = item["current_index"] != 0 and bool(item["version_labels"])
        label = QtWidgets.QLabel(item["label"])
        if marked:
            color = AM_TOKENS["text_muted"]
        elif outdated:
            color = AM_TOKENS["red_outdated_text"]
        else:
            color = AM_TOKENS["text_primary"]
        label.setStyleSheet(f"color:{color}; font-size:11px; font-weight:500;")
        font = label.font()
        font.setStrikeOut(marked)
        label.setFont(font)
        layout.addWidget(label, 1)

        # 2.24.5: Todd — "is there a good way to show which shade file is
        # attached to which cache.. just to show they are linked?" A
        # cache row shows which Shade asset it's merged onto; a Shade
        # asset row with one or more caches merged onto it shows a count
        # instead (so removing it isn't a surprise — see the cascade
        # logic in AssetManagerPanel._on_row_mark_toggle).
        link_label = None
        if item.get("is_cache"):
            asset_label = item.get("attached_asset_label")
            if asset_label:
                link_label = QtWidgets.QLabel(f"\U0001F517 {asset_label}")
                link_label.setToolTip(f"Cache merged onto Shade asset: {asset_label}")
        elif item.get("attached_cache_item_ids"):
            count = len(item["attached_cache_item_ids"])
            link_label = QtWidgets.QLabel(f"\U0001F517 {count} cache{'s' if count != 1 else ''}")
            link_label.setToolTip("Removing this asset will also remove the cache(s) merged onto it.")
        if link_label is not None:
            link_label.setStyleSheet(f"color:{AM_TOKENS['text_muted']}; font-size:9px; font-style:italic;")
            layout.addWidget(link_label)

        self.version_combo = QtWidgets.QComboBox()
        self.version_combo.setProperty("class", "amVersionCombo")
        self.version_combo.addItems(item["version_labels"] or ["-"])
        if item["version_labels"]:
            self.version_combo.setCurrentIndex(item["current_index"])
        self.version_combo.setEnabled(bool(item["version_labels"]) and not item["is_import"] and not marked)
        self.version_combo.setFixedWidth(60)
        self.version_combo.currentIndexChanged.connect(self.version_changed.emit)
        layout.addWidget(self.version_combo)

        if not marked:
            layout.addWidget(_am_status_pill(outdated))
        else:
            pending_label = QtWidgets.QLabel("PENDING")
            pending_label.setStyleSheet(
                f"background:{AM_TOKENS['red_status_bg']}; color:{AM_TOKENS['red_status_text']}; "
                f"font-size:8px; font-weight:700; border-radius:2px; padding:1px 5px;"
            )
            pending_label.setFixedHeight(14)
            layout.addWidget(pending_label)

        # 2.28.0: Import As dropdown — Import / Load [tracked] / Reference.
        # Asset rows only — caches attach to a node rather than being
        # referenced/imported as a file, so they don't get this control.
        self.import_mode_combo = None
        if not item.get("is_cache"):
            current_mode = item.get("import_mode", "reference")
            # Maya can bake a Reference into an Import (importReference)
            # but has no clean way back — so once a real (not freshly
            # staged) row is already an import, "Reference" is disabled
            # rather than offered and then failing at Update time.
            reference_locked = item["pending_state"] != "add" and item.get("is_import")

            mode_model = QtGui.QStandardItemModel()
            for mode in ASSET_MANAGER_IMPORT_MODE_ORDER:
                mode_item = QtGui.QStandardItem(ASSET_MANAGER_IMPORT_MODE_LABELS[mode])
                mode_item.setData(mode, QtCore.Qt.UserRole)
                if mode == "reference" and reference_locked:
                    mode_item.setFlags(mode_item.flags() & ~QtCore.Qt.ItemIsEnabled)
                mode_model.appendRow(mode_item)

            self.import_mode_combo = QtWidgets.QComboBox()
            self.import_mode_combo.setProperty("class", "amImportModeCombo")
            self.import_mode_combo.setModel(mode_model)
            self.import_mode_combo.setFixedWidth(80)
            try:
                mode_index = ASSET_MANAGER_IMPORT_MODE_ORDER.index(current_mode)
            except ValueError:
                mode_index = ASSET_MANAGER_IMPORT_MODE_ORDER.index("reference")
            self.import_mode_combo.setCurrentIndex(mode_index)
            if reference_locked:
                self.import_mode_combo.setToolTip(
                    "Already imported — Maya can't convert an import back into a Reference."
                )
            self.import_mode_combo.setEnabled(not marked)
            self.import_mode_combo.currentIndexChanged.connect(
                lambda i, c=self.import_mode_combo: self.import_mode_changed.emit(
                    c.itemData(i, QtCore.Qt.UserRole)
                )
            )
            layout.addWidget(self.import_mode_combo)

        # 2.23.4: switched from inline setStyleSheet to a QSS "class"
        # property so the shared stylesheet's :hover state actually
        # applies (inline per-widget stylesheets can't pick up :hover
        # rules defined in the panel-wide stylesheet).
        remove_btn = QtWidgets.QToolButton()
        remove_btn.setText("✕")
        remove_btn.setCursor(QtCore.Qt.PointingHandCursor)
        if marked:
            remove_btn.setProperty("class", "amRemoveBtnMarked")
            remove_btn.setToolTip("Marked for removal — click to undo, or Update to apply")
        else:
            remove_btn.setProperty("class", "amRemoveBtn")
            remove_btn.setToolTip("Mark for removal")
        remove_btn.clicked.connect(self.remove_clicked.emit)
        layout.addWidget(remove_btn)


class AssetManagerPanel(MayaQWidgetDockableMixin, QtWidgets.QWidget):
    """
    The new PySide Asset Manager panel — see the big comment block above
    show_asset_manager_window's replacement point for full context,
    design-token sourcing, and the documented deviations from the literal
    Claude Design mockup.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName(ASSET_MANAGER_PANEL_OBJECT_NAME)
        self.setWindowTitle(ASSET_MANAGER_PANEL_TITLE)
        self.setStyleSheet(_am_stylesheet())

        self.project_path = get_current_project(warn_if_missing=False)
        self.root_tab = "Assets"
        self.nav_level = "root"
        self.selected_shot = None
        self.selected_asset_type = None  # 2.27.0: which asset type (char/environ/prop/custom) is drilled into on the Assets tab
        self.selected_task = None  # 2.24.4: which task category (model/rig/lookdev/fx) is drilled into on the Assets tab
        self.scene_items = {}
        self.marked_for_removal = set()  # item ids toggled via the row's ✕ button
        self.pending_removals = []  # list of scene item dicts staged for removal on Update
        # 2.24.1: bumped every time a browse-list "+" stages another add,
        # so repeat-adding the same asset gets distinct scene_items keys
        # instead of colliding/overwriting — see _on_add_asset.
        self._next_add_instance_id = 1

        self._build_ui()
        self.refresh_from_scene()

    # ---------------- UI construction ----------------

    def _build_ui(self):
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        body = QtWidgets.QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        outer.addLayout(body, 1)

        # Nav rail
        nav_rail = QtWidgets.QWidget()
        nav_rail.setObjectName("amNavRail")
        # 2.24.6: Todd asked (again) for a vertical divider between the
        # nav rail and browse columns — it was already in the QSS
        # (border-right on #amNavRail/#amBrowseList, since 2.23.2) but
        # never actually rendered. Root cause: a plain QWidget doesn't
        # paint stylesheet background/border at all unless
        # WA_StyledBackground is set — QLabel/QPushButton/QFrame draw
        # their own backgrounds by default so this went unnoticed
        # everywhere else in the panel, but these three column
        # containers are bare QWidgets. Same fix applied to browse_col
        # and scene_col below.
        nav_rail.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        nav_rail.setFixedWidth(98)
        self.nav_layout = QtWidgets.QVBoxLayout(nav_rail)
        self.nav_layout.setContentsMargins(0, 0, 0, 0)
        self.nav_layout.setSpacing(0)
        self.nav_layout.addStretch(1)
        body.addWidget(nav_rail)

        # Browse list
        browse_col = QtWidgets.QWidget()
        browse_col.setObjectName("amBrowseList")
        browse_col.setAttribute(QtCore.Qt.WA_StyledBackground, True)  # 2.24.6 — see nav_rail's note above
        browse_col.setFixedWidth(236)
        browse_col_layout = QtWidgets.QVBoxLayout(browse_col)
        browse_col_layout.setContentsMargins(0, 0, 0, 0)
        browse_col_layout.setSpacing(0)
        self.browse_header = QtWidgets.QLabel("Assets")
        self.browse_header.setProperty("class", "amSectionHeader")
        browse_col_layout.addWidget(self.browse_header)
        self.browse_scroll = QtWidgets.QScrollArea()
        self.browse_scroll.setWidgetResizable(True)
        self.browse_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.browse_list_widget = QtWidgets.QWidget()
        self.browse_list_layout = QtWidgets.QVBoxLayout(self.browse_list_widget)
        self.browse_list_layout.setContentsMargins(4, 4, 4, 4)
        self.browse_list_layout.setSpacing(1)
        self.browse_list_layout.addStretch(1)
        self.browse_scroll.setWidget(self.browse_list_widget)
        browse_col_layout.addWidget(self.browse_scroll, 1)
        body.addWidget(browse_col)

        # In Scene column
        scene_col = QtWidgets.QWidget()
        scene_col.setObjectName("amSceneCol")
        scene_col.setAttribute(QtCore.Qt.WA_StyledBackground, True)  # 2.24.6 — see nav_rail's note above
        scene_col_layout = QtWidgets.QVBoxLayout(scene_col)
        scene_col_layout.setContentsMargins(0, 0, 0, 0)
        scene_col_layout.setSpacing(0)
        self.scene_header = QtWidgets.QLabel("In Scene — 0")
        self.scene_header.setProperty("class", "amSectionHeader")
        scene_col_layout.addWidget(self.scene_header)

        # 2.23.2: the old checkbox-driven multi-select bulk bar (Update to
        # Latest / Roll Back / Remove from Scene / Clear) is gone along
        # with the checkboxes it depended on — replaced by this simple
        # notice that appears once at least one row is marked ✕ for
        # removal, with a link to undo all marks at once.
        self.removal_bar = QtWidgets.QFrame()
        self.removal_bar.setObjectName("amRemovalBar")
        removal_layout = QtWidgets.QHBoxLayout(self.removal_bar)
        removal_layout.setContentsMargins(10, 6, 10, 6)
        removal_layout.setSpacing(6)
        self.removal_count_label = QtWidgets.QLabel("")
        self.removal_count_label.setStyleSheet(f"color:{AM_TOKENS['red_text']}; font-size:10.5px; font-weight:600;")
        removal_layout.addWidget(self.removal_count_label)
        removal_layout.addStretch(1)
        removal_undo = QtWidgets.QLabel("Undo All")
        removal_undo.setStyleSheet(f"color:{AM_TOKENS['red_text']}; font-size:10px; text-decoration: underline;")
        removal_undo.setCursor(QtCore.Qt.PointingHandCursor)
        removal_undo.mousePressEvent = lambda e: self._on_clear_marks()
        removal_layout.addWidget(removal_undo)
        self.removal_bar.setVisible(False)
        scene_col_layout.addWidget(self.removal_bar)

        self.scene_scroll = QtWidgets.QScrollArea()
        self.scene_scroll.setWidgetResizable(True)
        self.scene_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.scene_list_widget = QtWidgets.QWidget()
        self.scene_list_layout = QtWidgets.QVBoxLayout(self.scene_list_widget)
        self.scene_list_layout.setContentsMargins(0, 0, 0, 0)
        self.scene_list_layout.setSpacing(0)
        self.scene_list_layout.addStretch(1)
        self.scene_scroll.setWidget(self.scene_list_widget)
        scene_col_layout.addWidget(self.scene_scroll, 1)
        body.addWidget(scene_col, 1)

        # Footer
        footer = QtWidgets.QFrame()
        footer.setStyleSheet(f"background:{AM_TOKENS['bg_section_header']}; border-top:1px solid {AM_TOKENS['border']};")
        footer_layout = QtWidgets.QHBoxLayout(footer)
        footer_layout.setContentsMargins(10, 10, 10, 10)
        # 2.24.4: Todd — "i want the update button next to the cancel
        # button.. not all the way to the left.. just have it left of the
        # cancel button." Stretch now goes FIRST, pushing both buttons to
        # the right edge together instead of pinning Update to the far
        # left with a big gap before Cancel.
        footer_layout.addStretch(1)
        update_btn = QtWidgets.QPushButton("Update")
        update_btn.setProperty("class", "amFooterUpdate")
        update_btn.setCursor(QtCore.Qt.PointingHandCursor)
        update_btn.clicked.connect(self._on_update)
        footer_layout.addWidget(update_btn)
        cancel_btn = QtWidgets.QPushButton("Cancel")
        cancel_btn.setProperty("class", "amFooterCancel")
        cancel_btn.setCursor(QtCore.Qt.PointingHandCursor)
        cancel_btn.clicked.connect(self._on_cancel)
        footer_layout.addWidget(cancel_btn)
        outer.addWidget(footer)

    # ---------------- Refresh / rebuild ----------------

    def refresh_from_scene(self):
        """Re-seed everything from the actual current Maya scene state — discards any un-committed staged changes."""
        self.project_path = get_current_project(warn_if_missing=False)
        self.scene_items = _panel_seed_scene_items(self.project_path) if self.project_path else {}
        self.marked_for_removal = set()
        self.pending_removals = []
        self._next_add_instance_id = 1
        self._rebuild_nav()
        self._rebuild_browse_list()
        self._rebuild_scene_list()

    def _rebuild_nav(self):
        while self.nav_layout.count():
            child = self.nav_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        if self.nav_level == "root":
            tabs = [("Assets", self.root_tab == "Assets"), ("Shots", self.root_tab == "Shots")]
        elif self.nav_level == "asset_type":
            type_label = (self.selected_asset_type or "").capitalize()
            tabs = [("Back", False), (type_label, True)]
        elif self.nav_level == "asset_task":
            task_label = ASSET_MANAGER_CATEGORY_LABELS.get(self.selected_task, self.selected_task or "")
            tabs = [("Back", False), (task_label, True)]
        else:  # "shot"
            shot_label = self.selected_shot or ""
            tabs = [("Back", False), (shot_label, True)]

        for label, active in tabs:
            btn = QtWidgets.QPushButton(label)
            btn.setProperty("class", "amNavTabActive" if active else "amNavTab")
            btn.setCursor(QtCore.Qt.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, l=label: self._on_nav_click(l))
            self.nav_layout.addWidget(btn)
        self.nav_layout.addStretch(1)

    def _on_nav_click(self, label):
        if self.nav_level == "shot":
            if label == "Back":
                self.nav_level = "root"
                self.selected_shot = None
        elif self.nav_level == "asset_task":
            if label == "Back":
                self.nav_level = "asset_type"
                self.selected_task = None
        elif self.nav_level == "asset_type":
            if label == "Back":
                self.nav_level = "root"
                self.selected_asset_type = None
        else:
            if label in ("Assets", "Shots"):
                self.root_tab = label
        self._rebuild_nav()
        self._rebuild_browse_list()

    def _clear_layout(self, layout):
        while layout.count() > 1:  # keep the trailing stretch
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def _rebuild_browse_list(self):
        self._clear_layout(self.browse_list_layout)
        if not self.project_path:
            self.browse_header.setText("No project")
            return

        if self.nav_level == "shot":
            shot = self.selected_shot
            self.browse_header.setText(f"{shot} — Caches")
            items = _panel_shot_cache_items(self.project_path, shot)
            for entry in items:
                row = _AssetManagerBrowseRow(entry["name"], entry["sub"], has_add=True)
                row.add_clicked.connect(lambda e=entry: self._on_add_cache(e))
                self.browse_list_layout.insertWidget(self.browse_list_layout.count() - 1, row)
        elif self.nav_level == "asset_task":
            # 2.24.4: Todd — "if asset is clicked.. the second column
            # shows model / rig / lookdev.. then drill down into model or
            # rig or lookdev to get to the specific asset." This is that
            # drilled-in level — just the assets for self.selected_task
            # (2.27.0: further scoped to self.selected_asset_type). No
            # per-row type badge here (unlike the old flat list) since
            # the header/nav tab already names the category.
            task_label = ASSET_MANAGER_CATEGORY_LABELS.get(self.selected_task, self.selected_task or "")
            self.browse_header.setText(task_label)
            for entry in _panel_asset_browse_items(
                self.project_path, task_name=self.selected_task, type_name=self.selected_asset_type
            ):
                row = _AssetManagerBrowseRow(entry["name"], entry["sub"], has_add=True)
                row.add_clicked.connect(lambda e=entry: self._on_add_asset(e))
                self.browse_list_layout.insertWidget(self.browse_list_layout.count() - 1, row)
        elif self.nav_level == "asset_type":
            # 2.27.0: drilled into a Type (char/environ/prop/custom) —
            # shows the task-category list, scoped to that type, same as
            # the un-scoped list used to sit directly under the Assets tab.
            type_label = (self.selected_asset_type or "").capitalize()
            self.browse_header.setText(type_label)
            for entry in _panel_asset_task_category_items(self.project_path, type_name=self.selected_asset_type):
                row = _AssetManagerBrowseRow(entry["name"], entry["sub"], has_chevron=True)
                row.clicked.connect(lambda e=entry: self._on_open_asset_task(e))
                self.browse_list_layout.insertWidget(self.browse_list_layout.count() - 1, row)
        elif self.root_tab == "Assets":
            # 2.27.0: Assets tab's top-level browse list is now asset
            # Types (char/environ/prop/custom) — previously this listed
            # task categories directly, with Type skipped entirely.
            self.browse_header.setText("Assets")
            for entry in _panel_asset_type_items(self.project_path):
                row = _AssetManagerBrowseRow(entry["name"], entry["sub"], has_chevron=True)
                row.clicked.connect(lambda e=entry: self._on_open_asset_type(e))
                self.browse_list_layout.insertWidget(self.browse_list_layout.count() - 1, row)
        else:
            self.browse_header.setText("Shots")
            for entry in _panel_shot_browse_items(self.project_path):
                row = _AssetManagerBrowseRow(entry["name"], entry["sub"], has_chevron=True)
                row.clicked.connect(lambda e=entry: self._on_open_shot(e))
                self.browse_list_layout.insertWidget(self.browse_list_layout.count() - 1, row)

    def _on_open_asset_type(self, entry):
        self.nav_level = "asset_type"
        self.selected_asset_type = entry["type_name"]
        self._rebuild_nav()
        self._rebuild_browse_list()

    def _on_open_asset_task(self, entry):
        self.nav_level = "asset_task"
        self.selected_task = entry["task_name"]
        self._rebuild_nav()
        self._rebuild_browse_list()

    def _on_open_shot(self, entry):
        self.nav_level = "shot"
        self.selected_shot = entry["shot_name"]
        self._rebuild_nav()
        self._rebuild_browse_list()

    def _rebuild_scene_list(self):
        # 2.24.1: Todd — "[the right-hand list] can be broken up in
        # sections as well to.. in scene (list of items currently in
        # scene) and a horizontal break then importing (list of elements
        # being added to the scene)." Split into two top-level state
        # sections instead of one flat list: everything already real in
        # the scene ("existing"), then a divider, then anything staged
        # via the browse list's "+" and not yet committed ("add"). Since
        # 2.24.2 that "add" section can hold caches too, not just assets
        # — see _on_add_cache. The pre-existing Assets/Shots category
        # grouping is kept, but nested one level in — it only ever
        # matters for "In Scene" (a shot's caches only ever land there
        # under "Shots" once committed).
        self._clear_layout(self.scene_list_layout)
        self.scene_header.setText(f"In Scene — {len(self.scene_items)}")

        marked_count = len(self.marked_for_removal)
        if marked_count:
            self.removal_count_label.setText(
                f"{marked_count} marked for removal — click Update to apply, or click ✕ again to undo"
            )
            self.removal_bar.setVisible(True)
        else:
            self.removal_bar.setVisible(False)

        existing_items = [item for item in self.scene_items.values() if item["pending_state"] != "add"]
        importing_items = [item for item in self.scene_items.values() if item["pending_state"] == "add"]

        self._insert_scene_state_header("In Scene")
        if existing_items:
            for category in ("Assets", "Shots"):
                rows = [item for item in existing_items if item["category"] == category]
                if not rows:
                    continue
                group_header = QtWidgets.QLabel(category)
                group_header.setProperty("class", "amGroupHeader")
                self.scene_list_layout.insertWidget(self.scene_list_layout.count() - 1, group_header)
                for item in sorted(rows, key=lambda r: r["label"]):
                    self._insert_scene_row(item)
        else:
            empty_note = QtWidgets.QLabel("Nothing in the scene yet.")
            empty_note.setStyleSheet(f"color:{AM_TOKENS['text_muted']}; font-size:10px; padding:6px 10px;")
            self.scene_list_layout.insertWidget(self.scene_list_layout.count() - 1, empty_note)

        if importing_items:
            self._insert_scene_divider()
            self._insert_scene_state_header("Importing")
            for item in sorted(importing_items, key=lambda r: r["label"]):
                self._insert_scene_row(item)

    def _insert_scene_row(self, item):
        marked = item["id"] in self.marked_for_removal
        row_widget = _AssetManagerSceneRow(item, marked)
        row_widget.version_changed.connect(lambda idx, i=item["id"]: self._on_row_version_changed(i, idx))
        row_widget.remove_clicked.connect(lambda i=item["id"]: self._on_row_mark_toggle(i))
        row_widget.import_mode_changed.connect(lambda mode, i=item["id"]: self._on_row_import_mode_changed(i, mode))
        self.scene_list_layout.insertWidget(self.scene_list_layout.count() - 1, row_widget)

    def _insert_scene_state_header(self, text):
        header = QtWidgets.QLabel(text)
        header.setProperty("class", "amStateHeader")
        self.scene_list_layout.insertWidget(self.scene_list_layout.count() - 1, header)

    def _insert_scene_divider(self):
        divider = QtWidgets.QFrame()
        divider.setFixedHeight(2)
        divider.setStyleSheet(f"background:{AM_TOKENS['border_column']}; border:none; margin:6px 0px;")
        self.scene_list_layout.insertWidget(self.scene_list_layout.count() - 1, divider)

    # ---------------- Row-level actions (staged, not committed) ----------------

    def _on_row_version_changed(self, item_id, index):
        item = self.scene_items.get(item_id)
        if item and item["version_labels"]:
            item["current_index"] = index
            self._rebuild_scene_list()

    def _on_row_import_mode_changed(self, item_id, mode):
        # 2.28.0: just updates staged state -- nothing actually changes in
        # the scene until Update runs (see _do_update's mode-conversion
        # branch and the "add" branch's mode handling).
        item = self.scene_items.get(item_id)
        if item:
            item["import_mode"] = mode
            self._rebuild_scene_list()

    def _on_row_mark_toggle(self, item_id):
        # 2.23.2: no longer removes anything — just flips whether this
        # row is staged for removal on the next Update. See _on_update
        # for where marked rows actually get popped out of scene_items
        # and (for real, already-in-scene items) queued into
        # pending_removals.
        marking = item_id not in self.marked_for_removal
        if marking:
            self.marked_for_removal.add(item_id)
        else:
            self.marked_for_removal.discard(item_id)

        # 2.24.5: Todd — "cascade it" — marking a Shade asset for removal
        # also marks any cache(s) merged onto it, and un-marking the
        # asset undoes both together, so Update can never leave a cache
        # attached to a reference that's about to disappear. A cache
        # marked on its own (not via its asset) is unaffected.
        item = self.scene_items.get(item_id)
        if item:
            for cache_id in item.get("attached_cache_item_ids") or []:
                if cache_id not in self.scene_items:
                    continue
                if marking:
                    self.marked_for_removal.add(cache_id)
                else:
                    self.marked_for_removal.discard(cache_id)

        self._rebuild_scene_list()

    def _on_clear_marks(self):
        self.marked_for_removal = set()
        self._rebuild_scene_list()

    # ---------------- Add actions ----------------
    # 2.24.2: both assets and caches stage an "add" locally now — no scene
    # change until Update. (Through 2.24.1, caches committed immediately
    # via an auto-match-Shade-asset step; see _commit_cache_add's
    # docstring for that history and deviation #1 in the big comment
    # above this class for the underlying reason caches can't be
    # version-picked ahead of time the way assets can.)

    def _on_add_asset(self, entry):
        # 2.24.1: Todd — "the list of the assets available, should always
        # have a plus.. which means if the plus is clicked.. it adds it
        # to the column on the far right.. it doesnt import anything
        # immediately.. this allows the user to add as many as they
        # want to the scene." No more "already added -> skip" guard —
        # every click stages another entry, even for an asset/task
        # that's already staged or already in the scene, so the same
        # asset can be added more than once (e.g. multiple instances of
        # a prop) before Update actually commits anything. Each staged
        # add gets its own instance-suffixed id so it doesn't collide
        # with (or overwrite) an earlier add of the same asset/task.
        instance_id = f'{entry["id"]}#{self._next_add_instance_id}'
        self._next_add_instance_id += 1
        version_labels = _panel_version_labels(entry["available_versions"], is_cache=False)
        self.scene_items[instance_id] = {
            "id": instance_id,
            "label": f'{entry["name"]} — {ASSET_MANAGER_TASK_LABELS.get(entry["task_name"], entry["task_name"])}',
            "category": "Assets",
            "is_cache": False,
            "ref_node": None,
            "namespace": None,
            "asset_name": entry["asset_name"],
            "task_name": entry["task_name"],
            "asset_type": entry.get("asset_type"),  # 2.27.0 — resolves the exact type folder at commit time
            "available_versions": entry["available_versions"],
            "version_labels": version_labels,
            "current_index": 0,
            "original_index": None,
            "pending_state": "add",
            "is_import": False,
            # 2.28.0: defaults to Reference, same as the hardcoded
            # behavior before this feature existed. Changeable via the
            # row's new Import As dropdown before Update commits it.
            "import_mode": "reference",
            "original_import_mode": None,  # nothing committed yet -- not applicable
        }
        self._rebuild_browse_list()
        self._rebuild_scene_list()

    def _on_add_cache(self, entry):
        # 2.24.2: Todd — "do the same thing for cache" (as assets, in the
        # 2.24.1 round). No longer attaches/imports anything the moment
        # "+" is clicked — stages it into the "Importing" section instead,
        # exactly like an asset add. The actual auto-match-Shade-asset /
        # fall-back-to-default-shader work (previously all of this
        # method's body, see _commit_cache_add's docstring for that
        # history) now only runs at Update time. This also fixes the
        # "adding a cache wipes out staged assets" bug: the old version
        # ended with self.refresh_from_scene(), which re-seeds
        # scene_items from the real Maya scene and — since staged asset
        # adds don't exist in the real scene yet — silently dropped them.
        # Staging locally (like assets already do) means no
        # refresh_from_scene() call here, so switching between Assets and
        # a shot's caches and adding from both is properly additive.
        instance_id = f'{entry["shot_name"]}::{entry["cache_name"]}#{self._next_add_instance_id}'
        self._next_add_instance_id += 1
        version_labels = _panel_version_labels(entry["available_versions"], is_cache=True)
        self.scene_items[instance_id] = {
            "id": instance_id,
            "label": f'{entry["shot_name"]} — {entry["cache_name"]}',
            "category": "Shots",
            "is_cache": True,
            "cache_shot_name": entry["shot_name"],
            "cache_name": entry["cache_name"],
            "cache_obj_node": None,
            "available_versions": entry["available_versions"],
            "version_labels": version_labels,
            "current_index": 0,
            "original_index": None,
            "pending_state": "add",
            "is_import": False,
        }
        self._rebuild_browse_list()
        self._rebuild_scene_list()

    def _commit_cache_add(self, cache_file_path, cache_name, shot_name):
        """
        2.23.2: Todd — "when a cache is selected.. lets simplify the
        functionality: autoload the latest corresponding shade file. if
        there isnt one.. auto apply the generic shader to the cache."
        Auto-matches the cache to a same-named published Shade asset (same
        guess used in Import Caches — strip a trailing "_anim" suffix,
        case-insensitive exact match), references it, and attaches the
        cache at its latest version, no dialog. If there's no matching
        Shade asset (or its OBJ group is missing, or the attach fails for
        any reason) it falls straight back to importing the cache
        standalone with Maya's default shading group applied — same
        behavior as Import Caches' "Default Shader" option — so a cache is
        never left mid-flow waiting on a pick.

        2.24.2: this used to be the entire body of _on_add_cache and ran
        immediately on click; now it only runs from _do_update, once per
        staged "add" cache item, so a cache add is staged/discardable like
        everything else in this panel.
        """
        shade_assets = list_assets_with_task(self.project_path, "lookdev")
        guess = cache_name[:-5] if cache_name.lower().endswith("_anim") else cache_name
        matched_asset = next((a for a in shade_assets if a.lower() == guess.lower()), None)

        attached = False
        if matched_asset:
            asset_dir = find_asset_folder(self.project_path, matched_asset)
            versions = get_asset_task_versions(self.project_path, matched_asset, "lookdev") if asset_dir else []
            if asset_dir and versions:
                filename = versions[0]  # newest first
                namespace = _unique_reference_namespace(namespace_for_versioned_file(filename))
                shade_file_path = os.path.join(asset_task_source_dir(asset_dir, "lookdev"), filename)
                try:
                    cmds.file(shade_file_path, reference=True, namespace=namespace)
                    obj_node = f"{namespace}:OBJ"
                    if cmds.objExists(obj_node):
                        _attach_cache_to_node(cache_file_path, obj_node, asset_name=matched_asset)
                        _tag_cache_attachment(obj_node, shot_name, cache_name, filename=os.path.basename(cache_file_path))
                        print(f"Asset Manager: {cache_name} -> auto-matched {matched_asset} ({namespace}:OBJ)")
                        attached = True
                    else:
                        cmds.warning(
                            f'Auto-matched Shade asset "{matched_asset}" but its "OBJ" group was '
                            f"missing — importing {cache_name} with the default shader instead."
                        )
                        # 2.24.7 added an auto-cleanup here (removed the
                        # unused reference on failure) — REMOVED again in
                        # 2.24.12. Todd, correctly, pointed out this was
                        # exactly why 3 repeat attempts never showed 3
                        # distinct Shade references in the Outliner: each
                        # failed one got deleted before he could look at
                        # it, so every failed attempt kept recomputing the
                        # same freed "_2" namespace instead of "_2", "_3",
                        # "_4" — hiding the one thing that would actually
                        # show whether -connect is wiring onto the wrong
                        # (e.g. the first, already-successful) node instead
                        # of the fresh one. Left in the scene now on
                        # purpose so a failed attempt is fully inspectable.
                except Exception as e:
                    cmds.warning(
                        f"Could not attach auto-matched Shade asset for {cache_name}: {e} — "
                        "importing with the default shader instead."
                    )
                    # See the "OBJ missing" branch above — cleanup
                    # removed in 2.24.12 for the same reason.

        if not attached:
            self._add_cache_default_shader(cache_file_path, cache_name, shot_name)

    def _add_cache_default_shader(self, cache_file_path, cache_name, shot_name):
        """
        Import a cache standalone (no Shade asset to attach onto) and
        force-assign Maya's default shading group so the geo isn't left
        shaderless — identical logic to Import Caches' "Default Shader"
        option, kept in sync manually (see that window's docstring note
        on why the core attach logic is intentionally duplicated).

        2.24.7: now also tags the new node(s) via
        _tag_cache_standalone_nodes so these caches are tracked/counted
        by Asset Manager instead of the previous "known gap" of being
        completely invisible once they fell back to the default shader.

        2.24.9: now imports via _import_cache_standalone (namespaced)
        instead of a bare AbcImport — see that helper's docstring for
        why: a bare-named standalone import was the likely actual cause
        of later repeat-cache attaches failing.
        """
        try:
            new_nodes, _namespace = _import_cache_standalone(cache_file_path, cache_name)
        except Exception as e:
            cmds.warning(f"Could not import cache {cache_name}: {e}")
            return
        _tag_cache_standalone_nodes(new_nodes, shot_name, cache_name, filename=os.path.basename(cache_file_path))
        shapes = cmds.listRelatives(new_nodes, allDescendents=True, type="shape", fullPath=True) or [] if new_nodes else []
        if shapes:
            cmds.sets(shapes, edit=True, forceElement="initialShadingGroup")
        print(f"Asset Manager: {cache_name} -> imported with default shader ({len(new_nodes)} node(s))")

    # ---------------- Commit / discard ----------------

    def _on_update(self):
        # 2.23.3: Todd — "the update and cancel button arent functioning."
        # Couldn't reproduce without a live Maya session, so this wraps
        # the whole commit in a try/except that surfaces ANY unexpected
        # exception in a confirmDialog (previously an exception here
        # would print to the Script Editor at best — invisible if that
        # panel isn't open — and Todd would see literally nothing happen,
        # which matches "not functioning" exactly). Also: Update now
        # ALWAYS shows a confirmDialog, even on a true no-op (nothing
        # staged) — before this, a successful update with no errors only
        # `print()`ed, which is just as invisible as a swallowed
        # exception from the button's point of view. If this dialog
        # shows up naming a real error next time, that's the actual bug
        # to fix; if it shows "Nothing to update" every time it's
        # clicked, the click itself isn't reaching this handler at all
        # (a Maya/workspaceControl-level issue, not this code).
        try:
            self._do_update()
        except Exception as e:
            import traceback
            traceback.print_exc()
            cmds.confirmDialog(
                title="Asset Manager — Update Failed",
                message=f"Unexpected error, nothing was applied:\n\n{e}\n\n(Full traceback printed to the Script Editor.)",
                button=["OK"],
            )

    def _do_update(self):
        applied = 0
        errors = []

        # 2.23.2: apply any ✕-marked rows first — pop them out of
        # scene_items and, for ones that were actually already in the
        # scene, queue them into pending_removals same as before.
        for item_id in list(self.marked_for_removal):
            item = self.scene_items.pop(item_id, None)
            if item and item["pending_state"] == "existing":
                self.pending_removals.append(item)
        self.marked_for_removal = set()

        for item in self.pending_removals:
            try:
                if item["is_cache"]:
                    node = item["cache_obj_node"]
                    # 2.24.5: with cascade removal, a cache's obj_node can
                    # legitimately already be gone by the time this runs —
                    # if its Shade asset's reference was ALSO marked for
                    # removal and happened to process first, removing that
                    # reference already deleted the node (and everything
                    # merged onto it) along with it. Nothing left to clean
                    # up in that case; just skip rather than error.
                    if node and cmds.objExists(node):
                        # 2.24.9: a cache with no attached Shade asset
                        # (item["attached_namespace"] is None) is a
                        # standalone Default Shader import — obj_node IS
                        # the cache's own geometry root, not something
                        # merged onto real asset geo. Removing it used to
                        # only delete the AlembicNode + tag attrs, leaving
                        # the actual geometry sitting in the scene forever
                        # (untracked, since its tags were just cleared) —
                        # exactly the kind of leftover "OBJ"/"OBJ1" node
                        # that turned out to break later cache attaches
                        # (see _add_cache_default_shader's 2.24.9 note).
                        # Delete the whole node outright in that case
                        # instead of just detaching/untagging it. A cache
                        # actually merged onto a Shade asset still only
                        # gets detached — deleting node there would delete
                        # the Shade asset's own real geometry.
                        if not item.get("attached_namespace"):
                            cmds.delete(node)
                        else:
                            for old_node in _find_connected_alembic_nodes(node):
                                cmds.delete(old_node)
                            for attr in (CACHE_ATTR_SHOT, CACHE_ATTR_NAME, CACHE_ATTR_FILE):
                                if cmds.attributeQuery(attr, node=node, exists=True):
                                    cmds.deleteAttr(f"{node}.{attr}")
                elif item["is_import"]:
                    cmds.namespace(removeNamespace=item["namespace"], deleteNamespaceContent=True)
                elif item["ref_node"]:
                    cmds.file(referenceNode=item["ref_node"], removeReference=True)
                applied += 1
            except Exception as e:
                errors.append(f"{item['label']}: could not remove ({e})")

        for item in self.scene_items.values():
            if item["is_cache"]:
                if item["pending_state"] == "add":
                    # 2.24.2: cache adds are staged now (like assets) —
                    # this is where the auto-match-Shade/attach (or
                    # default-shader fallback) actually happens.
                    try:
                        filename = item["available_versions"][item["current_index"]]
                        cache_dir = get_shot_cache_dir(self.project_path, item["cache_shot_name"])
                        cache_file_path = os.path.join(cache_dir, filename)
                        self._commit_cache_add(cache_file_path, item["cache_name"], item["cache_shot_name"])
                        applied += 1
                    except Exception as e:
                        errors.append(f"{item['label']}: could not add cache ({e})")
                    continue
                if item["current_index"] == item.get("original_index"):
                    continue  # no version change staged
                try:
                    new_filename = item["available_versions"][item["current_index"]]
                    cache_dir = get_shot_cache_dir(self.project_path, item["cache_shot_name"])
                    # 2.31.12: use the resolved (possibly re-parented)
                    # node _attach_cache_to_node actually attached onto —
                    # see that function's 2.31.12 note. Traceback from
                    # Todd's 2.31.11 test confirmed the attach/swap
                    # itself was already succeeding by this point; the
                    # crash was _tag_cache_attachment still being handed
                    # the pre-grouping obj_node one line down.
                    resolved_obj_node = _attach_cache_to_node(
                        os.path.join(cache_dir, new_filename), item["cache_obj_node"]
                    )
                    _tag_cache_attachment(
                        resolved_obj_node, item["cache_shot_name"], item["cache_name"], filename=new_filename
                    )
                    item["cache_obj_node"] = resolved_obj_node
                    applied += 1
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    errors.append(f"{item['label']}: could not swap cache version ({e})")
                continue

            if item["pending_state"] == "add":
                asset_type = item.get("asset_type")
                if asset_type:
                    candidate = os.path.join(self.project_path, "assets", asset_type, item["asset_name"])
                    asset_dir = candidate if os.path.isdir(candidate) else None
                else:
                    asset_dir = find_asset_folder(self.project_path, item["asset_name"])
                if not asset_dir:
                    errors.append(f"{item['label']}: asset folder not found")
                    continue
                filename = item["available_versions"][item["current_index"]]
                file_path = os.path.join(asset_task_source_dir(asset_dir, item["task_name"]), filename)
                # 2.24.1: uniquified, not the bare namespace_for_versioned_file()
                # result — the same asset/version can now be staged (and
                # therefore referenced) more than once in one Update.
                namespace = _unique_reference_namespace(namespace_for_versioned_file(filename))
                # 2.28.0: Todd — "asset manager import as options". Three
                # ways to bring the file in, picked via the row's Import As
                # dropdown (default "reference", unchanged prior behavior):
                #   reference         -> cmds.file(reference=True, ...)
                #   import_tracked    -> cmds.file(i=True, namespace=<versioned>, ...)
                #                        keeps the "<asset>_<task>_vNNN" namespace
                #                        convention so _asset_manager_collect_imported_rows
                #                        still finds/tracks it on the next refresh.
                #   import_untracked  -> cmds.file(i=True, namespace=":", ...)
                #                        flat import, no namespace -- not
                #                        discoverable/tracked once the scene
                #                        is refreshed, by design.
                mode = item.get("import_mode", "reference")
                try:
                    obj_node = None
                    if mode == "reference":
                        cmds.file(file_path, reference=True, namespace=namespace)
                        obj_node = f"{namespace}:OBJ"
                    elif mode == "import_tracked":
                        cmds.file(file_path, i=True, namespace=namespace, ignoreVersion=True)
                        obj_node = f"{namespace}:OBJ"
                    else:  # import_untracked
                        new_nodes = cmds.file(
                            file_path,
                            i=True,
                            namespace=":",
                            mergeNamespacesOnClash=True,
                            ignoreVersion=True,
                            returnNewNodes=True,
                        ) or []
                        # No namespace to build the OBJ node's name from --
                        # find it among the nodes Maya actually just created.
                        obj_node = next(
                            (n for n in new_nodes if re.match(r"^OBJ\d*$", n.rsplit("|", 1)[-1])), None
                        )
                    # 2.24.17/2.28.0: Todd — individual (non-cache) asset
                    # adds through this panel's own "+" were a third,
                    # separate code path from do_add()
                    # (show_asset_manager_add_window) and _commit_cache_add,
                    # and never got the 2.24.15/16 OBJ-grouping fix — so a
                    # Shade asset added here still ended up sitting at DAG
                    # root with a plain/no group, not matching the
                    # "<asset>_<task>_<number>" convention. Applies
                    # regardless of which of the three modes it came in
                    # through — only lookdev (Shade) has a cache-attach
                    # target worth grouping.
                    if item["task_name"] == "lookdev" and obj_node and cmds.objExists(obj_node):
                        _ensure_obj_node_grouped(
                            obj_node, asset_name=item["asset_name"], task_name=item["task_name"]
                        )
                    applied += 1
                except Exception as e:
                    errors.append(f"{item['label']}: could not add ({e})")
                continue

            # 2.28.0: an already-in-scene asset's Import As mode was
            # changed via its row dropdown. Handle before any version swap
            # below, since converting reference -> import changes what
            # item["ref_node"]/["namespace"] actually point at.
            mode = item.get("import_mode", "reference")
            original_mode = item.get("original_import_mode", "reference")
            if mode != original_mode:
                try:
                    if original_mode == "reference" and mode in ("import_tracked", "import_untracked"):
                        # Maya can bake a Reference into an Import cleanly;
                        # the namespace survives the bake as-is.
                        cmds.file(importReference=True, referenceNode=item["ref_node"])
                        item["ref_node"] = None
                        item["is_import"] = True
                        if mode == "import_untracked" and item.get("namespace"):
                            cmds.namespace(removeNamespace=item["namespace"], mergeNamespaceWithRoot=True)
                            item["namespace"] = None
                        applied += 1
                    elif original_mode == "import_tracked" and mode == "import_untracked":
                        if item.get("namespace"):
                            cmds.namespace(removeNamespace=item["namespace"], mergeNamespaceWithRoot=True)
                            item["namespace"] = None
                        applied += 1
                    elif mode == "reference":
                        # Blocked in the UI already (the dropdown disables
                        # "Reference" once a row is an import) -- this is
                        # just a defensive guard in case that ever drifts
                        # out of sync with _do_update.
                        errors.append(f"{item['label']}: can't convert an import back to a Reference")
                    else:
                        errors.append(
                            f"{item['label']}: can't change Import As mode ({original_mode} -> {mode})"
                        )
                except Exception as e:
                    errors.append(f"{item['label']}: could not change Import As mode ({e})")

            if item["is_import"] or item["current_index"] == item.get("original_index"):
                continue  # nothing to change (import rows can't be version-swapped)

            try:
                new_filename = item["available_versions"][item["current_index"]]
                asset_dir = find_asset_folder(self.project_path, item["asset_name"])
                new_path = os.path.join(asset_task_source_dir(asset_dir, item["task_name"]), new_filename)
                cmds.file(new_path, loadReference=item["ref_node"])
                try:
                    old_namespace = cmds.referenceQuery(item["ref_node"], namespace=True).lstrip(":")
                    new_namespace = namespace_for_versioned_file(new_filename)
                    if old_namespace and old_namespace != new_namespace:
                        cmds.namespace(rename=(old_namespace, new_namespace))
                except Exception as e:
                    errors.append(f"{item['label']}: swapped version but could not rename namespace ({e})")
                applied += 1
            except Exception as e:
                errors.append(f"{item['label']}: could not swap version ({e})")

        # 2.23.3: always confirmDialog, not just on errors — a silent
        # `print()`-only success looked identical to "the button did
        # nothing" from Todd's side if the Script Editor wasn't open.
        if errors:
            cmds.confirmDialog(
                title="Asset Manager",
                message="Applied {} change(s).\n\nSome changes could not be applied:\n{}".format(
                    applied, "\n".join(errors)
                ),
                button=["OK"],
            )
        elif applied:
            print(f"Asset Manager: applied {applied} change(s).")
            cmds.confirmDialog(title="Asset Manager", message=f"Applied {applied} change(s).", button=["OK"])
        else:
            cmds.confirmDialog(title="Asset Manager", message="Nothing to update — no changes staged.", button=["OK"])

        self.refresh_from_scene()

        # 2.24.18: Todd — "lets close the asset manager down when the
        # user clicks update.. (after performing the tasks)". Matches
        # Cancel's close() behavior (2.23.4) — same try/except guard so a
        # close failure doesn't mask whatever Update itself already did.
        try:
            self.close()
        except Exception:
            pass

    def _on_cancel(self):
        # 2.23.4: Todd — "cancel should close the popup window.... its
        # currently not doing anything." Reverses the original 2.23.0
        # design call (discard-and-stay-open, matching a persistent
        # docked panel) — Cancel now discards any staged changes AND
        # closes the panel, same as a normal dialog's Cancel. `self.close()`
        # on a MayaQWidgetDockableMixin widget also tears down its
        # workspaceControl, so this closes the floating window entirely,
        # not just hides it. The 2.23.3 "Discarded N staged change(s)"
        # dialog is gone — with the window itself closing, that's already
        # unambiguous visible feedback, and a confirmDialog the user has
        # to click through right before the window disappears anyway was
        # just an extra click for no benefit now that Cancel does
        # something undeniable. try/except kept from 2.23.3 so a genuine
        # error here still surfaces instead of failing silently.
        try:
            self.close()
        except Exception as e:
            import traceback
            traceback.print_exc()
            cmds.confirmDialog(
                title="Asset Manager — Cancel Failed",
                message=f"Unexpected error while cancelling:\n\n{e}\n\n(Full traceback printed to the Script Editor.)",
                button=["OK"],
            )


def show_asset_manager_panel():
    """
    Open (or bring forward) the new PySide Asset Manager dock panel. See
    the big comment block above AssetManagerPanel for design-mockup
    sourcing and documented deviations.
    """
    project_path = get_current_project()
    if not project_path:
        return

    workspace_control_name = ASSET_MANAGER_PANEL_OBJECT_NAME + "WorkspaceControl"
    if cmds.workspaceControl(workspace_control_name, exists=True):
        cmds.deleteUI(workspace_control_name)

    panel = AssetManagerPanel()
    # 2.23.1: floating rather than docked to the right side by default —
    # floating=True still opens it via MayaQWidgetDockableMixin (so it
    # CAN be dragged into a dock later), it just doesn't auto-dock on
    # open.
    # 2.23.2: Todd — "make the window overall 2x wider and half as
    # high.. things were feeling cramped." 660x520 -> 1320x260. The Nav
    # rail (98px) and Browse list (236px) stay their original fixed
    # widths — all the extra width goes to the flexible In Scene column,
    # which is the one that was actually feeling tight.
    panel.show(dockable=True, floating=True, width=1320, height=260)
    return panel


# ---------------- Import Caches panel (2.24.0) ----------------
# Todd, after the Asset Manager panel work landed: "i would love to apply
# the same aesthetic to the import caches menu." This rebuilds
# show_import_caches_window (the original cmds.window version, kept
# intact below unchanged/unwired as a fallback — same "leave the old one
# standalone" pattern used for show_asset_manager_window during the
# 2.23.0 overhaul) as a PySide floating panel sharing AM_TOKENS and
# _am_stylesheet() with the Asset Manager panel — same dark background,
# JetBrains-Mono version dropdowns, green Import / neutral Cancel footer
# buttons with the same hover/pressed states. Every bit of underlying
# logic (auto-match by stripped "_anim" suffix, the "Default Shader"
# fallback, per-row reference+AbcImport-connect via
# _attach_cache_to_node/_tag_cache_attachment, and the succeeded/
# skipped/failed summary dialog) is carried over unchanged — this pass
# only replaces the widget toolkit and visuals, not the import logic.

IMPORT_CACHES_SHOT_PLACEHOLDER = "Select a shot..."
IMPORT_CACHES_NAME_PLACEHOLDER = "Name"
IMPORT_CACHES_VER_PLACEHOLDER = "Ver"
IMPORT_CACHES_DEFAULT_SHADER_LABEL = "Default Shader"


class _ImportCachesRow(QtWidgets.QFrame):
    """One cache row: checkbox, cache name + version, Shade asset + version."""

    def __init__(self, cache_name, cache_versions, shade_assets, matched_asset, project_path, parent=None):
        super().__init__(parent)
        self.setObjectName("icRow")
        self.cache_name = cache_name
        self.project_path = project_path

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(8)

        self.checkbox = QtWidgets.QCheckBox()
        self.checkbox.setProperty("class", "icRowCheck")
        self.checkbox.setChecked(True)
        self.checkbox.setCursor(QtCore.Qt.PointingHandCursor)
        self.checkbox.setFixedWidth(20)
        layout.addWidget(self.checkbox)

        name_label = QtWidgets.QLabel(cache_name)
        name_label.setStyleSheet(f"color:{AM_TOKENS['text_primary']}; font-size:11px; font-weight:500;")
        name_label.setFixedWidth(160)
        layout.addWidget(name_label)

        # Cache Ver dropdown — newest first, no placeholder needed, same
        # as the original cmds version (get_shot_cache_names guarantees
        # at least one file exists for every stub it returns).
        self.cache_ver_lookup = {}
        self.cache_ver_combo = QtWidgets.QComboBox()
        self.cache_ver_combo.setProperty("class", "amVersionCombo")
        self.cache_ver_combo.setFixedWidth(60)
        for filename in cache_versions:
            match = CACHE_VERSIONED_FILE_PATTERN.match(filename)
            label = f"v{match.group(2)}" if match else filename
            self.cache_ver_lookup[label] = filename
            self.cache_ver_combo.addItem(label)
        layout.addWidget(self.cache_ver_combo)

        layout.addSpacing(20)  # 2.22.6-equivalent breathing room before Shade Asset/Ver

        self.shade_combo = QtWidgets.QComboBox()
        self.shade_combo.setProperty("class", "amShadeCombo")
        self.shade_combo.setFixedWidth(160)
        self.shade_combo.addItem(IMPORT_CACHES_NAME_PLACEHOLDER)
        self.shade_combo.addItem(IMPORT_CACHES_DEFAULT_SHADER_LABEL)
        for asset_name in shade_assets:
            self.shade_combo.addItem(asset_name)
        if matched_asset:
            self.shade_combo.setCurrentText(matched_asset)
        layout.addWidget(self.shade_combo)

        self.shade_ver_lookup = {}
        self.shade_ver_combo = QtWidgets.QComboBox()
        self.shade_ver_combo.setProperty("class", "amVersionCombo")
        self.shade_ver_combo.setFixedWidth(60)
        layout.addWidget(self.shade_ver_combo)
        layout.addStretch(1)

        self.shade_combo.currentTextChanged.connect(self._refresh_shade_versions)
        self._refresh_shade_versions()

    def _refresh_shade_versions(self, *_args):
        self.shade_ver_combo.blockSignals(True)
        self.shade_ver_combo.clear()
        self.shade_ver_lookup.clear()
        asset_name = self.shade_combo.currentText()

        if asset_name == IMPORT_CACHES_DEFAULT_SHADER_LABEL:
            self.shade_ver_combo.addItem("—")
            self.shade_ver_combo.setEnabled(False)
        else:
            self.shade_ver_combo.setEnabled(True)
            self.shade_ver_combo.addItem(IMPORT_CACHES_VER_PLACEHOLDER)
            if asset_name != IMPORT_CACHES_NAME_PLACEHOLDER:
                filenames = get_asset_task_versions(self.project_path, asset_name, "lookdev")
                for filename in filenames:
                    match = VERSIONED_FILE_PATTERN.match(filename)
                    label = f"v{match.group(2)}" if match else filename
                    self.shade_ver_lookup[label] = filename
                    self.shade_ver_combo.addItem(label)
                if filenames:
                    # Pre-select latest — same "Cache" dropdown exception as
                    # the rest of this file (2.20.4 precedent); every other
                    # dropdown here still forces an explicit pick.
                    latest_match = VERSIONED_FILE_PATTERN.match(filenames[0])
                    latest_label = f"v{latest_match.group(2)}" if latest_match else filenames[0]
                    self.shade_ver_combo.setCurrentText(latest_label)
        self.shade_ver_combo.blockSignals(False)


class ImportCachesPanel(MayaQWidgetDockableMixin, QtWidgets.QWidget):
    """The new PySide Import Caches panel — see the module comment above for context."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName(IMPORT_CACHES_PANEL_OBJECT_NAME)
        self.setWindowTitle(IMPORT_CACHES_PANEL_TITLE)
        self.setStyleSheet(_am_stylesheet())

        self.project_path = get_current_project(warn_if_missing=False)
        self.rows = []

        self._build_ui()
        self._populate_shots()

    def _build_ui(self):
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QtWidgets.QLabel("Import Caches")
        header.setProperty("class", "amSectionHeader")
        outer.addWidget(header)

        top_bar = QtWidgets.QFrame()
        top_bar.setStyleSheet(f"background:{AM_TOKENS['bg_dark_column']};")
        top_layout = QtWidgets.QHBoxLayout(top_bar)
        top_layout.setContentsMargins(10, 8, 10, 8)
        shot_label = QtWidgets.QLabel("Shot")
        shot_label.setStyleSheet(f"color:{AM_TOKENS['text_muted_alt']}; font-size:10.5px; font-weight:600;")
        top_layout.addWidget(shot_label)
        self.shot_combo = QtWidgets.QComboBox()
        self.shot_combo.setProperty("class", "amShadeCombo")
        self.shot_combo.setFixedWidth(180)
        self.shot_combo.currentTextChanged.connect(self._refresh_rows)
        top_layout.addWidget(self.shot_combo)
        top_layout.addStretch(1)
        outer.addWidget(top_bar)

        col_header = QtWidgets.QFrame()
        col_header.setObjectName("icHeaderRow")
        col_header_layout = QtWidgets.QHBoxLayout(col_header)
        col_header_layout.setContentsMargins(10, 4, 10, 4)
        col_header_layout.setSpacing(8)

        def _h(text, width):
            lbl = QtWidgets.QLabel(text)
            lbl.setStyleSheet(f"color:{AM_TOKENS['text_muted']}; font-size:9.5px; font-weight:700;")
            lbl.setFixedWidth(width)
            return lbl

        col_header_layout.addWidget(_h("", 20))
        col_header_layout.addWidget(_h("Cache", 160))
        col_header_layout.addWidget(_h("Ver", 60))
        col_header_layout.addSpacing(20)
        col_header_layout.addWidget(_h("Shade Asset", 160))
        col_header_layout.addWidget(_h("Ver", 60))
        col_header_layout.addStretch(1)
        outer.addWidget(col_header)

        self.rows_scroll = QtWidgets.QScrollArea()
        self.rows_scroll.setWidgetResizable(True)
        self.rows_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.rows_widget = QtWidgets.QWidget()
        self.rows_widget.setStyleSheet(f"background:{AM_TOKENS['bg_dark_column']};")
        self.rows_layout = QtWidgets.QVBoxLayout(self.rows_widget)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(0)
        self.rows_layout.addStretch(1)
        self.rows_scroll.setWidget(self.rows_widget)
        outer.addWidget(self.rows_scroll, 1)

        footer = QtWidgets.QFrame()
        footer.setStyleSheet(f"background:{AM_TOKENS['bg_section_header']}; border-top:1px solid {AM_TOKENS['border']};")
        footer_layout = QtWidgets.QHBoxLayout(footer)
        footer_layout.setContentsMargins(10, 10, 10, 10)
        footer_layout.addStretch(1)
        import_btn = QtWidgets.QPushButton("Import")
        import_btn.setProperty("class", "amFooterUpdate")
        import_btn.setCursor(QtCore.Qt.PointingHandCursor)
        import_btn.clicked.connect(self._on_import)
        footer_layout.addWidget(import_btn)
        cancel_btn = QtWidgets.QPushButton("Cancel")
        cancel_btn.setProperty("class", "amFooterCancel")
        cancel_btn.setCursor(QtCore.Qt.PointingHandCursor)
        cancel_btn.clicked.connect(self._on_cancel)
        footer_layout.addWidget(cancel_btn)
        outer.addWidget(footer)

    def _populate_shots(self):
        self.shot_combo.blockSignals(True)
        self.shot_combo.clear()
        self.shot_combo.addItem(IMPORT_CACHES_SHOT_PLACEHOLDER)
        if self.project_path:
            for shot_name in list_existing_shots(self.project_path):
                self.shot_combo.addItem(shot_name)
        self.shot_combo.blockSignals(False)
        self._refresh_rows()

    def _clear_rows(self):
        while self.rows_layout.count() > 1:  # keep the trailing stretch
            child = self.rows_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self.rows = []

    def _placeholder(self, text):
        label = QtWidgets.QLabel(text)
        label.setStyleSheet(f"color:{AM_TOKENS['text_muted']}; font-size:10.5px; padding:10px;")
        self.rows_layout.insertWidget(self.rows_layout.count() - 1, label)

    def _refresh_rows(self, *_args):
        self._clear_rows()
        shot_name = self.shot_combo.currentText()
        if not self.project_path or not shot_name or shot_name == IMPORT_CACHES_SHOT_PLACEHOLDER:
            self._placeholder("Select a shot to see its caches.")
            return

        cache_names = get_shot_cache_names(self.project_path, shot_name)
        if not cache_names:
            self._placeholder(f'No caches found for shot "{shot_name}".')
            return

        shade_assets = list_assets_with_task(self.project_path, "lookdev")
        for cache_name in cache_names:
            cache_versions = get_shot_cache_versions(self.project_path, shot_name, cache_name)
            # Auto-match, same guess as everywhere else in this file:
            # strip a trailing "_anim" suffix, case-insensitive exact
            # match against a published Shade asset name.
            guess = cache_name[:-5] if cache_name.lower().endswith("_anim") else cache_name
            matched_asset = next((a for a in shade_assets if a.lower() == guess.lower()), None)
            row = _ImportCachesRow(cache_name, cache_versions, shade_assets, matched_asset, self.project_path)
            self.rows_layout.insertWidget(self.rows_layout.count() - 1, row)
            self.rows.append(row)

    def _on_import(self):
        try:
            self._do_import()
        except Exception as e:
            import traceback
            traceback.print_exc()
            cmds.confirmDialog(
                title="Import Caches — Import Failed",
                message=f"Unexpected error, nothing was applied:\n\n{e}\n\n(Full traceback printed to the Script Editor.)",
                button=["OK"],
            )

    def _do_import(self):
        shot_name = self.shot_combo.currentText()
        if not shot_name or shot_name == IMPORT_CACHES_SHOT_PLACEHOLDER:
            cmds.warning("Select a shot first.")
            return
        if not self.rows:
            cmds.warning("No caches to import.")
            return

        cache_dir = get_shot_cache_dir(self.project_path, shot_name)
        succeeded = []
        skipped_unset = []
        failed = []
        any_checked = False

        for row in self.rows:
            if not row.checkbox.isChecked():
                continue
            any_checked = True

            cache_label = row.cache_ver_combo.currentText()
            cache_filename = row.cache_ver_lookup.get(cache_label)
            asset_name = row.shade_combo.currentText()

            if asset_name == IMPORT_CACHES_NAME_PLACEHOLDER or not cache_filename:
                skipped_unset.append(row.cache_name)
                continue

            cache_file_path = os.path.join(cache_dir, cache_filename)

            if asset_name == IMPORT_CACHES_DEFAULT_SHADER_LABEL:
                # 2.24.9: namespaced import (_import_cache_standalone) —
                # see that helper's docstring for why a bare-named
                # standalone import was the likely cause of later
                # repeat-cache attaches failing.
                try:
                    new_nodes, _namespace = _import_cache_standalone(cache_file_path, row.cache_name)
                except Exception as e:
                    failed.append(f"{row.cache_name}: could not import cache: {e}")
                    continue
                shapes = cmds.listRelatives(new_nodes, allDescendents=True, type="shape", fullPath=True) or [] if new_nodes else []
                if shapes:
                    cmds.sets(shapes, edit=True, forceElement="initialShadingGroup")
                # 2.24.7: tag so Asset Manager tracks/counts this cache
                # too instead of it being invisible once it falls back to
                # the default shader (see _tag_cache_standalone_nodes).
                _tag_cache_standalone_nodes(new_nodes, shot_name, row.cache_name, filename=cache_filename)
                succeeded.append(f"{row.cache_name} -> default shader ({len(new_nodes)} node(s))")
                continue

            asset_ver_label = row.shade_ver_combo.currentText()
            asset_filename = row.shade_ver_lookup.get(asset_ver_label)
            if not asset_filename:
                skipped_unset.append(row.cache_name)
                continue

            asset_dir = find_asset_folder(self.project_path, asset_name)
            if not asset_dir:
                failed.append(f'{row.cache_name}: could not find asset folder for "{asset_name}".')
                continue

            shade_file_path = os.path.join(asset_task_source_dir(asset_dir, "lookdev"), asset_filename)
            namespace = namespace_for_versioned_file(asset_filename)
            try:
                cmds.file(shade_file_path, reference=True, namespace=namespace)
            except Exception as e:
                failed.append(f"{row.cache_name}: could not reference {shade_file_path}: {e}")
                continue

            obj_node = f"{namespace}:OBJ"
            if not cmds.objExists(obj_node):
                failed.append(
                    f'{row.cache_name}: referenced "{asset_name}" but no "{obj_node}" group found — cache not imported.'
                )
                # 2.24.7 added cleanup here — REMOVED in 2.24.12, see the
                # matching note in AssetManagerPanel._commit_cache_add:
                # leaving a failed attempt's reference in the scene is
                # what actually lets it be inspected/diagnosed.
                continue

            try:
                # connect=, not reparent= — see the 2.21.3 fix note on
                # show_cache_shade_picker_window's on_import. Routed
                # through the shared helpers so this attachment also
                # shows up in Asset Manager and can be versioned there.
                _attach_cache_to_node(cache_file_path, obj_node, asset_name=asset_name)
                _tag_cache_attachment(obj_node, shot_name, row.cache_name, filename=os.path.basename(cache_file_path))
            except Exception as e:
                failed.append(f'{row.cache_name}: referenced "{asset_name}" but could not import cache: {e}')
                # See the branch above — cleanup removed in 2.24.12.
                continue

            succeeded.append(f"{row.cache_name} -> {asset_name} ({namespace}:OBJ)")

        if not any_checked:
            cmds.warning("Nothing checked to import.")
            return

        lines = []
        if succeeded:
            lines.append(f"Imported {len(succeeded)}:")
            lines.extend(succeeded)
        if skipped_unset:
            if lines:
                lines.append("")
            lines.append(
                "Skipped (pick a Shade asset + version, or Default Shader): " + ", ".join(skipped_unset)
            )
        if failed:
            if lines:
                lines.append("")
            lines.append("Failed:")
            lines.extend(failed)

        if lines:
            cmds.confirmDialog(title="Import Caches", message="\n".join(lines), button=["OK"])

        try:
            self.close()
        except Exception:
            pass  # already reported a real success/failure summary above; don't mask it with a close error

    def _on_cancel(self):
        try:
            self.close()
        except Exception as e:
            import traceback
            traceback.print_exc()
            cmds.confirmDialog(
                title="Import Caches — Cancel Failed",
                message=f"Unexpected error while cancelling:\n\n{e}\n\n(Full traceback printed to the Script Editor.)",
                button=["OK"],
            )


def show_import_caches_panel():
    """
    Open (or bring forward) the new PySide Import Caches panel (2.24.0).
    Todd: "i would love to apply the same aesthetic to the import caches
    menu." See the module comment above ImportCachesPanel for what
    carried over unchanged from show_import_caches_window (kept intact
    below, unwired, as a fallback/rollback — same pattern used for
    show_asset_manager_window during the 2.23.0 overhaul).
    """
    project_path = get_current_project()
    if not project_path:
        return

    workspace_control_name = IMPORT_CACHES_PANEL_OBJECT_NAME + "WorkspaceControl"
    if cmds.workspaceControl(workspace_control_name, exists=True):
        cmds.deleteUI(workspace_control_name)

    panel = ImportCachesPanel()
    panel.show(dockable=True, floating=True, width=640, height=420)
    return panel


def get_next_asset_version(folder_path, filename_stub):
    """Scan folder_path for <filename_stub>.vNNN.ext files and return the next version number (1 if none exist yet)."""
    highest = 0
    if os.path.isdir(folder_path):
        pattern = re.compile(rf"^{re.escape(filename_stub)}\.v(\d+)\.(ma|mb)$", re.IGNORECASE)
        for name in os.listdir(folder_path):
            match = pattern.match(name)
            if match:
                highest = max(highest, int(match.group(1)))
    return highest + 1


def align_maya_project():
    """
    Set Maya's current workspace to whichever project is appropriate for
    wherever the current scene was just saved: the nearest ancestor folder
    containing a workspace.mel (typically an asset's own "maya" folder),
    walking up from the scene's location. Falls back to the tracked
    pipeline project root if no workspace.mel is found along the way.
    """
    scene_path = cmds.file(query=True, sceneName=True)
    if scene_path:
        current_dir = os.path.dirname(scene_path)
        while current_dir:
            if os.path.isfile(os.path.join(current_dir, "workspace.mel")):
                cmds.workspace(current_dir, openWorkspace=True)
                return
            parent_dir = os.path.dirname(current_dir)
            if parent_dir == current_dir:
                break
            current_dir = parent_dir

    project_path = get_current_project(warn_if_missing=False)
    if project_path and os.path.isdir(project_path):
        cmds.workspace(project_path, openWorkspace=True)


def _maya_folder_from_scene_path(scene_path):
    """
    Given a saved scene's file path, return the <task>/work/maya folder it
    sits under, or None if it doesn't sit under one at all. Handles the
    file sitting directly IN that maya folder (the convention before
    2.31.4) as well as in its maya/scenes subfolder (the convention as of
    2.31.4 — see asset_task_scenes_dir's docstring / [[folder_structure]]),
    so existing scenes saved the old way keep resolving correctly
    alongside newly-saved ones.
    """
    parent_dir = os.path.dirname(scene_path)
    if os.path.basename(parent_dir) == "maya":
        return parent_dir
    if os.path.basename(parent_dir) == "scenes":
        maybe_maya_dir = os.path.dirname(parent_dir)
        if os.path.basename(maybe_maya_dir) == "maya":
            return maybe_maya_dir
    return None


def _task_name_from_scene_path(scene_path):
    """
    Given a saved scene's file path, return the task folder name if it
    sits at the standard <task>/work/maya(/scenes)/<file> location — the
    layout every asset task (model/rig/lookdev/fx) and every shot task
    with Maya files now uses, see ASSET_TASKS / SHOT_TASK_STRUCTURE —
    else None. Used by Setup Scene and Publish to know which task a scene
    belongs to without asking, just from where it's saved.
    """
    maya_dir = _maya_folder_from_scene_path(scene_path)
    if not maya_dir:
        return None
    work_dir = os.path.dirname(maya_dir)
    if os.path.basename(work_dir) != "work":
        return None
    task_dir = os.path.dirname(work_dir)
    return os.path.basename(task_dir) or None


def create_asset_folder_structure(*_args):
    """
    "Create Asset Folders" — Data Manager menu item (renamed/moved from
    "Create Asset" under Asset Manager in 2.22.7). Prompts for an asset
    type and name, then builds that asset's full folder structure (model/
    rig/lookdev/fx/texture task folders, each with work/output as
    appropriate via build_asset_task_structure) with no scene save
    involved. This is the only place a brand-new asset's folders get
    created now — Save As's Asset Name field is a dropdown of existing
    assets only, per Todd: typing a name by hand on Save As risks a
    mismatch, so asset creation is split out into its own explicit step
    here.
    """
    project_path = get_current_project()
    if not project_path:
        return

    asset_type = prompt_asset_type_choice()
    if not asset_type:
        return

    asset_name = _prompt_for_name("Create Asset Folders", "Asset Name:")
    if not asset_name:
        return

    asset_dir = os.path.join(project_path, "assets", asset_type, asset_name)
    already_existed = os.path.isdir(asset_dir)
    build_asset_task_structure(asset_dir)

    if already_existed:
        print(f"Create Asset Folders: '{asset_name}' already existed, filled in any missing task folders.")
        cmds.confirmDialog(
            title="Asset Folder Ready",
            message=f'"{asset_name}" already existed — missing task folders (if any) were filled in.',
            button=["OK"],
        )
    else:
        print(f"Create Asset Folders: created '{asset_name}' ({asset_type}) at {asset_dir}")
        cmds.confirmDialog(
            title="Asset Created",
            message=f'Created asset "{asset_name}" ({asset_type}):\n{asset_dir}',
            button=["OK"],
        )


# ------------------------------------------------------------------
# Export / Import Pipeline (2.24.20, overhauled to v2 in 2.25.0,
# rebuilt as v3 in 2.26.0)
# ------------------------------------------------------------------
# Todd: share folder-structure info with an outside collaborator (e.g. a
# freelance modeler on one character, or an animator on a handful of
# shots) without handing them the whole project. Export writes a small
# JSON manifest listing which assets and/or shots to include — structure
# only, no scene files — and Import rebuilds exactly those folders
# wherever the recipient points it, using the SAME folder-building
# functions (build_asset_task_structure/build_shot_task_structure,
# accepting an optional `tasks` subset — see their 2.24.20 notes) every
# other asset/shot creation flow in this file already uses, so this can
# never drift out of sync with whatever the folder convention is at
# import time.
#
# 2.26.0 REDESIGN (superseding 2.25.0's 4-item submenus + task-level
# checkbox picker, discussed with Todd before building — see
# [[pipeline_package]] project memory): the whole feature is now a
# single Export Pipeline / Import Pipeline menu item each, opening a
# PySide (NOT dockable — Todd: "i dont actually want either of them
# pyside dockable") 3-column window styled after Asset Manager
# (AM_TOKENS/_am_stylesheet, _AssetManagerBrowseRow). Task-level picking
# is gone — each asset/shot is staged as a whole unit ("only as far as
# the folder names.. no need to look at the data beyond that"), every
# task folder it has gets built.
#
# Export Pipeline (ExportPipelinePanel):
#   Column 1: current project name (static label).
#   Column 2: Assets/Shots tabs. Assets drills into a type (char/
#     environ/prop) then individual asset names; Shots lists shot names
#     directly. Each leaf item has a "+" (Asset Manager's Add Asset
#     pattern) that stages it into Column 3.
#   Column 3: staged items, each with a "✕" to unstage.
#   Footer: Full Project / All Shots / All Assets / Export / Cancel.
#     The three "All ..." buttons ADD to whatever's already staged
#     (so e.g. "All Assets" can be combined with a couple of
#     hand-picked shots) rather than replacing it. Nothing is written
#     until Export is clicked.
#   Export writes straight into <project>/io/data xfer/ — no save
#   dialog (Todd: "lets save all this in a common location.. in the
#   root of every project.. theres an io folder.. put it in there" /
#   "label the folder 'data xfer' so it aligns with the menu function").
#
# Import Pipeline (show_import_pipeline_package -> ImportPipelinePanel):
#   1. Native file-browse dialog to locate the package .json (Todd:
#      "on import.. first have them point to the file"). Filter reads
#      "JSON (*.json)" — Todd flagged the old "Pipeline Package
#      (*.json)" filter text as confusing.
#   2. A confirm dialog checks the current projects root
#      (get_projects_root() — the same root scan_projects_root() uses
#      to build the Project switcher radio menu) and offers "Change"
#      (browse to a different root, via the existing
#      select_project_root()) or "OK" (accept it as-is). Whichever root
#      is settled on is where <root>/<package's project_name> gets
#      created (or reused, if a project by that name already lives
#      there).
#   3. Main 3-column window: Column 1 = package's project name.
#      Column 2 = Full/Custom toggle — Full stages everything from the
#      package straight into Column 3; Custom switches Column 2 to the
#      same Assets/Shots drill-down as Export, red/yellow color-coded
#      against what already exists at the destination (red = brand new,
#      yellow = exists locally but missing at least one task folder the
#      package has), with the same "+" staging.
#      Column 3: staged items. Footer: Import / Cancel.

PIPELINE_PACKAGE_VERSION = 3  # 2.26.0 — whole-item packages, no per-task picking
PIPELINE_PACKAGE_DATA_XFER_SUBDIR = "data xfer"  # <project>/io/<this>/ — Export's fixed auto-save location

SHOT_TASK_LABELS = {
    "anim": "Anim",
    "comp": "Comp",
    "design": "Design",
    "dmp": "DMP",
    "fx": "FX",
    "lighting": "Lighting",
    "previs": "Previs",
}


def _all_assets_for_package(project_path):
    """Every asset in the project, in pipeline-package manifest shape (every task it could have)."""
    return [
        {
            "asset_name": asset_name,
            "asset_type": os.path.basename(os.path.dirname(asset_dir)),
            "tasks": list(ASSET_TASKS),
        }
        for asset_name, asset_dir in list_all_assets(project_path)
    ]


def _all_shots_for_package(project_path):
    """Every shot in the project, in pipeline-package manifest shape (every task it could have)."""
    return [
        {"shot_name": shot_name, "tasks": list(SHOT_TASK_STRUCTURE.keys())}
        for shot_name in list_existing_shots(project_path)
    ]


def _current_pipeline_package_settings():
    """Current project settings (shot prefix, output size, frame range) — carried along with every export."""
    return {
        "shot_prefix": cmds.optionVar(query=SHOT_PREFIX_OPTVAR) if cmds.optionVar(exists=SHOT_PREFIX_OPTVAR) else None,
        "output_width": cmds.optionVar(query=OUTPUT_WIDTH_OPTVAR) if cmds.optionVar(exists=OUTPUT_WIDTH_OPTVAR) else None,
        "output_height": cmds.optionVar(query=OUTPUT_HEIGHT_OPTVAR)
        if cmds.optionVar(exists=OUTPUT_HEIGHT_OPTVAR)
        else None,
        "start_frame": cmds.optionVar(query=START_FRAME_OPTVAR) if cmds.optionVar(exists=START_FRAME_OPTVAR) else None,
        "end_frame": cmds.optionVar(query=END_FRAME_OPTVAR) if cmds.optionVar(exists=END_FRAME_OPTVAR) else None,
    }


def _pipeline_package_export_dir(project_path):
    """<project>/io/data xfer — created on demand."""
    out_dir = os.path.join(project_path, "io", PIPELINE_PACKAGE_DATA_XFER_SUBDIR)
    os.makedirs(out_dir, exist_ok=True)
    return out_dir


def _write_pipeline_package(project_path, assets, shots):
    """
    Write the manifest straight into <project>/io/data xfer/<project>_<timestamp>.json
    — no save dialog (2.26.0). Returns the path written, or None on failure.
    """
    project_name = os.path.basename(project_path.rstrip(os.sep))
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    export_path = os.path.join(_pipeline_package_export_dir(project_path), f"{project_name}_{stamp}.json")

    manifest = {
        "pipeline_package_version": PIPELINE_PACKAGE_VERSION,
        "project_name": project_name,
        "assets": assets,
        "shots": shots,
        "settings": _current_pipeline_package_settings(),
    }
    try:
        with open(export_path, "w") as f:
            json.dump(manifest, f, indent=2)
    except Exception as e:
        cmds.warning(f"Could not write pipeline package: {e}")
        return None
    return export_path


def _load_pipeline_package_file():
    """Prompt for a manifest .json and return its parsed contents, or None if cancelled/invalid."""
    result = cmds.fileDialog2(fileMode=1, caption="Select Pipeline Package", fileFilter="JSON (*.json)")
    if not result:
        return None
    try:
        with open(result[0], "r") as f:
            manifest = json.load(f)
    except Exception as e:
        cmds.warning(f"Could not read pipeline package: {e}")
        return None

    if manifest.get("pipeline_package_version") != PIPELINE_PACKAGE_VERSION:
        cmds.warning(
            "This pipeline package was made with a different or unrecognized version — importing anyway, "
            "but double-check the result."
        )
    return manifest


def _apply_pipeline_package_settings(manifest):
    """Restore shot prefix / output size / frame range from a package, and apply to the open scene."""
    settings = manifest.get("settings")
    if not settings:
        return
    if settings.get("shot_prefix"):
        cmds.optionVar(stringValue=(SHOT_PREFIX_OPTVAR, settings["shot_prefix"]))
    if settings.get("output_width") is not None and settings.get("output_height") is not None:
        cmds.optionVar(intValue=(OUTPUT_WIDTH_OPTVAR, settings["output_width"]))
        cmds.optionVar(intValue=(OUTPUT_HEIGHT_OPTVAR, settings["output_height"]))
    if settings.get("start_frame") is not None:
        cmds.optionVar(intValue=(START_FRAME_OPTVAR, settings["start_frame"]))
    if settings.get("end_frame") is not None:
        cmds.optionVar(intValue=(END_FRAME_OPTVAR, settings["end_frame"]))
    apply_saved_settings()


def _build_pipeline_package_items(project_path, assets, shots):
    """Build exactly the given asset/shot entries (list of manifest dicts). Returns (asset_lines, shot_lines)."""
    asset_lines = []
    for asset in assets:
        asset_name = asset.get("asset_name")
        asset_type = asset.get("asset_type")
        tasks = asset.get("tasks") or []
        if not asset_name or not asset_type or not tasks:
            continue
        asset_dir = os.path.join(project_path, "assets", asset_type, asset_name)
        build_asset_task_structure(asset_dir, tasks=tasks)
        asset_lines.append(f'{asset_name} ({asset_type}): {", ".join(tasks)}')

    shot_lines = []
    for shot in shots:
        shot_name = shot.get("shot_name")
        tasks = shot.get("tasks") or []
        if not shot_name or not tasks:
            continue
        shot_path = os.path.join(project_path, "shots", shot_name)
        os.makedirs(shot_path, exist_ok=True)
        build_shot_task_structure(shot_path, tasks=tasks)
        shot_lines.append(f'{shot_name}: {", ".join(tasks)}')

    return asset_lines, shot_lines


def _show_pipeline_package_import_summary(project_path, project_name, already_existed, asset_lines, shot_lines):
    summary = f"Project {'(new) ' if not already_existed else ''}{project_name}\n{project_path}\n\n"
    summary += "Assets:\n  " + ("\n  ".join(asset_lines) if asset_lines else "(none)") + "\n\n"
    summary += "Shots:\n  " + ("\n  ".join(shot_lines) if shot_lines else "(none)")
    cmds.confirmDialog(title="Pipeline Package Imported", message=summary, button=["OK"])


# ---------------- Shared 3-column panel bits ----------------

def _pipeline_panel_type_items(project_path):
    """Export/Import Custom Assets root: one entry per asset type folder (char/environ/prop)."""
    items = []
    for type_name in STANDARD_ASSET_TYPES:
        type_path = os.path.join(project_path, "assets", type_name)
        count = len([n for n in os.listdir(type_path) if os.path.isdir(os.path.join(type_path, n))]) if os.path.isdir(type_path) else 0
        items.append({"id": type_name, "name": type_name.capitalize(), "sub": f"{count} asset{'s' if count != 1 else ''}"})
    return items


class _PipelineStagedRow(QtWidgets.QFrame):
    """One row in a Pipeline panel's Column 3 (staged) list — label + a remove '✕'."""

    remove_clicked = QtCore.Signal()

    def __init__(self, label, sub, parent=None):
        super().__init__(parent)
        self.setObjectName("amSceneRow")
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(6)

        text_col = QtWidgets.QVBoxLayout()
        text_col.setSpacing(1)
        name_label = QtWidgets.QLabel(label)
        name_label.setStyleSheet(f"color:{AM_TOKENS['text_primary']}; font-size:11px; font-weight:500;")
        text_col.addWidget(name_label)
        if sub:
            sub_label = QtWidgets.QLabel(sub)
            sub_label.setStyleSheet(f"color:{AM_TOKENS['text_muted']}; font-size:9.5px;")
            text_col.addWidget(sub_label)
        layout.addLayout(text_col, 1)

        remove_btn = QtWidgets.QToolButton()
        remove_btn.setText("✕")
        remove_btn.setCursor(QtCore.Qt.PointingHandCursor)
        remove_btn.setProperty("class", "amRemoveBtn")
        remove_btn.setToolTip("Remove from staged list")
        remove_btn.clicked.connect(self.remove_clicked.emit)
        layout.addWidget(remove_btn)


class _PipelineBasePanel(QtWidgets.QWidget):
    """
    Shared 3-column scaffold for ExportPipelinePanel/ImportPipelinePanel —
    a static-label left column, a browse/nav middle column, and a staged
    (Column 3) list with a footer button row. Not a MayaQWidgetDockableMixin
    — plain floating QWidget top-levels only (Todd: not dockable).
    """

    def __init__(self, object_name, title, parent=None):
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setWindowTitle(title)
        self.setWindowFlags(QtCore.Qt.Window)
        self.setStyleSheet(_am_stylesheet())

        self.staged = {}  # (kind, name) -> entry dict, in stage order

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.body = QtWidgets.QHBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(0)
        outer.addLayout(self.body, 1)

        # Column 1 — project name, static.
        col1 = QtWidgets.QWidget()
        col1.setObjectName("amNavRail")
        col1.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        col1.setFixedWidth(150)
        col1_layout = QtWidgets.QVBoxLayout(col1)
        col1_layout.setContentsMargins(10, 10, 10, 10)
        col1_layout.setSpacing(2)
        project_header = QtWidgets.QLabel("Project")
        project_header.setStyleSheet(f"color:{AM_TOKENS['text_muted']}; font-size:9.5px; font-weight:600;")
        col1_layout.addWidget(project_header)
        self.project_name_label = QtWidgets.QLabel("")
        self.project_name_label.setWordWrap(True)
        self.project_name_label.setStyleSheet(f"color:{AM_TOKENS['text_active']}; font-size:12px; font-weight:600;")
        col1_layout.addWidget(self.project_name_label)
        col1_layout.addStretch(1)
        self.body.addWidget(col1)

        # Column 2 — browse/nav (built by subclasses via _build_column2).
        self.col2 = QtWidgets.QWidget()
        self.col2.setObjectName("amBrowseList")
        self.col2.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.col2.setFixedWidth(260)
        self.col2_layout = QtWidgets.QVBoxLayout(self.col2)
        self.col2_layout.setContentsMargins(0, 0, 0, 0)
        self.col2_layout.setSpacing(0)
        self.body.addWidget(self.col2)

        # Column 3 — staged items.
        col3 = QtWidgets.QWidget()
        col3.setObjectName("amSceneCol")
        col3.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        col3_layout = QtWidgets.QVBoxLayout(col3)
        col3_layout.setContentsMargins(0, 0, 0, 0)
        col3_layout.setSpacing(0)
        self.staged_header = QtWidgets.QLabel("Staged — 0")
        self.staged_header.setProperty("class", "amSectionHeader")
        col3_layout.addWidget(self.staged_header)
        self.staged_scroll = QtWidgets.QScrollArea()
        self.staged_scroll.setWidgetResizable(True)
        self.staged_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.staged_list_widget = QtWidgets.QWidget()
        self.staged_list_layout = QtWidgets.QVBoxLayout(self.staged_list_widget)
        self.staged_list_layout.setContentsMargins(0, 0, 0, 0)
        self.staged_list_layout.setSpacing(0)
        self.staged_list_layout.addStretch(1)
        self.staged_scroll.setWidget(self.staged_list_widget)
        col3_layout.addWidget(self.staged_scroll, 1)
        self.body.addWidget(col3, 1)

        # Footer — subclasses add their own buttons via _build_footer_buttons.
        footer = QtWidgets.QFrame()
        footer.setStyleSheet(f"background:{AM_TOKENS['bg_section_header']}; border-top:1px solid {AM_TOKENS['border']};")
        self.footer_layout = QtWidgets.QHBoxLayout(footer)
        self.footer_layout.setContentsMargins(10, 10, 10, 10)
        self.footer_layout.addStretch(1)
        self._build_footer_buttons(self.footer_layout)
        outer.addWidget(footer)

        self.resize(760, 480)

    # ---- staged-list management, shared by both panels ----

    def _stage(self, kind, name, entry):
        self.staged[(kind, name)] = entry
        self._refresh_staged_list()

    def _stage_many(self, entries):
        """entries: list of (kind, name, entry) — merges into whatever's already staged."""
        for kind, name, entry in entries:
            self.staged[(kind, name)] = entry
        self._refresh_staged_list()

    def _unstage(self, kind, name):
        self.staged.pop((kind, name), None)
        self._refresh_staged_list()

    def _refresh_staged_list(self):
        while self.staged_list_layout.count() > 1:
            item = self.staged_list_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        self.staged_header.setText(f"Staged — {len(self.staged)}")
        for (kind, name), entry in self.staged.items():
            label = f"{name} ({entry.get('asset_type')})" if kind == "asset" and entry.get("asset_type") else name
            sub = "Asset" if kind == "asset" else "Shot"
            row = _PipelineStagedRow(label, sub)
            row.remove_clicked.connect(lambda k=kind, n=name: self._unstage(k, n))
            self.staged_list_layout.insertWidget(self.staged_list_layout.count() - 1, row)

    # ---- subclass hooks ----

    def _build_column2(self):
        raise NotImplementedError

    def _build_footer_buttons(self, layout):
        raise NotImplementedError


def _pipeline_panel_show(panel):
    """
    Show a Pipeline panel as a plain floating top-level — parented to
    Maya's main window (via MQtUtil) purely so it doesn't get lost behind
    the Maya viewport, NOT so it can dock (Todd: not dockable).
    """
    try:
        main_window_ptr = omui.MQtUtil.mainWindow()
        maya_main_window = _am_wrap_instance(int(main_window_ptr), QtWidgets.QWidget) if main_window_ptr else None
    except Exception:
        maya_main_window = None
    if maya_main_window is not None:
        panel.setParent(maya_main_window, QtCore.Qt.Window)
    panel.show()
    panel.raise_()
    panel.activateWindow()


# ---------------- Export Pipeline ----------------

class ExportPipelinePanel(_PipelineBasePanel):
    def __init__(self, project_path, parent=None):
        self.project_path = project_path
        self.nav_tab = "Assets"  # "Assets" or "Shots"
        self.asset_type = None  # set once drilled into a type on the Assets tab
        super().__init__(EXPORT_PIPELINE_PANEL_OBJECT_NAME, EXPORT_PIPELINE_PANEL_TITLE, parent=parent)
        self.project_name_label.setText(os.path.basename(project_path.rstrip(os.sep)))
        self._build_column2()

    def _build_footer_buttons(self, layout):
        full_btn = QtWidgets.QPushButton("Full Project")
        full_btn.setProperty("class", "amFooterCancel")
        full_btn.setCursor(QtCore.Qt.PointingHandCursor)
        full_btn.clicked.connect(self._on_full_project)
        layout.addWidget(full_btn)

        all_shots_btn = QtWidgets.QPushButton("All Shots")
        all_shots_btn.setProperty("class", "amFooterCancel")
        all_shots_btn.setCursor(QtCore.Qt.PointingHandCursor)
        all_shots_btn.clicked.connect(self._on_all_shots)
        layout.addWidget(all_shots_btn)

        all_assets_btn = QtWidgets.QPushButton("All Assets")
        all_assets_btn.setProperty("class", "amFooterCancel")
        all_assets_btn.setCursor(QtCore.Qt.PointingHandCursor)
        all_assets_btn.clicked.connect(self._on_all_assets)
        layout.addWidget(all_assets_btn)

        export_btn = QtWidgets.QPushButton("Export")
        export_btn.setProperty("class", "amFooterUpdate")
        export_btn.setCursor(QtCore.Qt.PointingHandCursor)
        export_btn.clicked.connect(self._on_export)
        layout.addWidget(export_btn)

        cancel_btn = QtWidgets.QPushButton("Cancel")
        cancel_btn.setProperty("class", "amFooterCancel")
        cancel_btn.setCursor(QtCore.Qt.PointingHandCursor)
        cancel_btn.clicked.connect(self.close)
        layout.addWidget(cancel_btn)

    # ---- Column 2 ----

    def _build_column2(self):
        while self.col2_layout.count():
            item = self.col2_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        tab_row = QtWidgets.QWidget()
        tab_row_layout = QtWidgets.QHBoxLayout(tab_row)
        tab_row_layout.setContentsMargins(0, 0, 0, 0)
        tab_row_layout.setSpacing(0)
        for tab_name in ("Assets", "Shots"):
            btn = QtWidgets.QPushButton(tab_name)
            btn.setProperty("class", "amNavTabActive" if tab_name == self.nav_tab else "amNavTab")
            btn.setCursor(QtCore.Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, t=tab_name: self._on_tab_clicked(t))
            tab_row_layout.addWidget(btn)
        self.col2_layout.addWidget(tab_row)

        self.browse_header = QtWidgets.QLabel()
        self.browse_header.setProperty("class", "amSectionHeader")
        self.col2_layout.addWidget(self.browse_header)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        list_widget = QtWidgets.QWidget()
        self.browse_list_layout = QtWidgets.QVBoxLayout(list_widget)
        self.browse_list_layout.setContentsMargins(4, 4, 4, 4)
        self.browse_list_layout.setSpacing(1)
        self.browse_list_layout.addStretch(1)
        scroll.setWidget(list_widget)
        self.col2_layout.addWidget(scroll, 1)

        self._refresh_browse_list()

    def _on_tab_clicked(self, tab_name):
        self.nav_tab = tab_name
        self.asset_type = None
        self._build_column2()

    def _clear_browse_rows(self):
        while self.browse_list_layout.count() > 1:
            item = self.browse_list_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _refresh_browse_list(self):
        self._clear_browse_rows()

        if self.nav_tab == "Shots":
            self.browse_header.setText("Shots")
            for shot_name in list_existing_shots(self.project_path):
                row = _AssetManagerBrowseRow(shot_name, "Shot", has_add=True)
                row.add_clicked.connect(lambda n=shot_name: self._stage_single_shot(n))
                self.browse_list_layout.insertWidget(self.browse_list_layout.count() - 1, row)
            return

        # Assets tab.
        if self.asset_type is None:
            self.browse_header.setText("Assets")
            for entry in _pipeline_panel_type_items(self.project_path):
                row = _AssetManagerBrowseRow(entry["name"], entry["sub"], has_chevron=True)
                row.clicked.connect(lambda t=entry["id"]: self._drill_into_type(t))
                self.browse_list_layout.insertWidget(self.browse_list_layout.count() - 1, row)
        else:
            self.browse_header.setText(self.asset_type.capitalize())
            type_path = os.path.join(self.project_path, "assets", self.asset_type)
            asset_names = sorted(n for n in os.listdir(type_path) if os.path.isdir(os.path.join(type_path, n))) if os.path.isdir(type_path) else []
            for asset_name in asset_names:
                row = _AssetManagerBrowseRow(asset_name, "Asset", has_add=True)
                row.add_clicked.connect(lambda n=asset_name, t=self.asset_type: self._stage_single_asset(n, t))
                self.browse_list_layout.insertWidget(self.browse_list_layout.count() - 1, row)

    def _drill_into_type(self, type_name):
        self.asset_type = type_name
        self._refresh_browse_list()

    # ---- staging ----

    def _stage_single_asset(self, asset_name, asset_type):
        entry = {"asset_name": asset_name, "asset_type": asset_type, "tasks": list(ASSET_TASKS)}
        self._stage("asset", asset_name, entry)

    def _stage_single_shot(self, shot_name):
        entry = {"shot_name": shot_name, "tasks": list(SHOT_TASK_STRUCTURE.keys())}
        self._stage("shot", shot_name, entry)

    def _on_full_project(self):
        self._stage_many(
            [("asset", a["asset_name"], a) for a in _all_assets_for_package(self.project_path)]
            + [("shot", s["shot_name"], s) for s in _all_shots_for_package(self.project_path)]
        )

    def _on_all_assets(self):
        self._stage_many([("asset", a["asset_name"], a) for a in _all_assets_for_package(self.project_path)])

    def _on_all_shots(self):
        self._stage_many([("shot", s["shot_name"], s) for s in _all_shots_for_package(self.project_path)])

    def _on_export(self):
        if not self.staged:
            cmds.warning("Stage at least one asset or shot first.")
            return
        assets = [entry for (kind, _name), entry in self.staged.items() if kind == "asset"]
        shots = [entry for (kind, _name), entry in self.staged.items() if kind == "shot"]
        export_path = _write_pipeline_package(self.project_path, assets, shots)
        if not export_path:
            return
        self.close()
        cmds.confirmDialog(
            title="Pipeline Exported",
            message=f"Exported {len(assets)} asset(s) and {len(shots)} shot(s) to:\n{export_path}",
            button=["OK"],
        )


def show_export_pipeline_panel():
    """Menu entry point — Export Pipeline."""
    project_path = get_current_project()
    if not project_path:
        return
    panel = ExportPipelinePanel(project_path)
    _pipeline_panel_show(panel)
    return panel


# ---------------- Import Pipeline ----------------

def _pipeline_import_destination_root():
    """
    Step 2 of Import Pipeline: confirm/choose the projects root the new
    project folder gets created under — the SAME root get_projects_root()/
    scan_projects_root() use for the Project switcher. Returns the root
    path, or None if the user backs out entirely.
    """
    current_root = get_projects_root()
    if current_root:
        choice = cmds.confirmDialog(
            title="Projects Location",
            message=f"New project will be placed in:\n{current_root}",
            button=["OK", "Change"],
            defaultButton="OK",
            cancelButton="Change",
        )
        if choice == "OK":
            return current_root
        # "Change" falls through to the same browse-and-set flow used
        # when there's no root configured yet.

    result = cmds.fileDialog2(fileMode=3, caption="Select Projects Folder", okCaption="Set")
    if not result:
        return None
    new_root = result[0]
    cmds.optionVar(stringValue=(PROJECTS_ROOT_OPTVAR, new_root))
    cmds.savePrefs(general=True)
    cmds.evalDeferred(build_menu)
    return new_root


def show_import_pipeline_package():
    """
    Menu entry point — Import Pipeline. File-browse for the package first,
    then confirm/choose the destination projects root, then open the main
    3-column window.
    """
    manifest = _load_pipeline_package_file()
    if not manifest:
        return
    project_name = manifest.get("project_name")
    if not project_name:
        cmds.warning("This pipeline package has no project name in it — cannot import.")
        return

    root_path = _pipeline_import_destination_root()
    if not root_path:
        return

    project_path = os.path.join(root_path, project_name)
    already_existed = os.path.isdir(project_path)

    panel = ImportPipelinePanel(manifest, project_path, already_existed)
    _pipeline_panel_show(panel)
    return panel


class ImportPipelinePanel(_PipelineBasePanel):
    def __init__(self, manifest, project_path, already_existed, parent=None):
        self.manifest = manifest
        self.project_path = project_path
        self.already_existed = already_existed
        self.mode = "Full"  # "Full" or "Custom"
        self.nav_tab = "Assets"  # Custom mode only
        self.asset_type = None  # Custom mode only, once drilled into a type
        super().__init__(IMPORT_PIPELINE_PANEL_OBJECT_NAME, IMPORT_PIPELINE_PANEL_TITLE, parent=parent)
        self.project_name_label.setText(manifest.get("project_name", ""))
        self._build_column2()

    def _build_footer_buttons(self, layout):
        import_btn = QtWidgets.QPushButton("Import")
        import_btn.setProperty("class", "amFooterUpdate")
        import_btn.setCursor(QtCore.Qt.PointingHandCursor)
        import_btn.clicked.connect(self._on_import)
        layout.addWidget(import_btn)

        cancel_btn = QtWidgets.QPushButton("Cancel")
        cancel_btn.setProperty("class", "amFooterCancel")
        cancel_btn.setCursor(QtCore.Qt.PointingHandCursor)
        cancel_btn.clicked.connect(self.close)
        layout.addWidget(cancel_btn)

    # ---- Column 2 ----

    def _build_column2(self):
        while self.col2_layout.count():
            item = self.col2_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        toggle_row = QtWidgets.QWidget()
        toggle_row_layout = QtWidgets.QHBoxLayout(toggle_row)
        toggle_row_layout.setContentsMargins(0, 0, 0, 0)
        toggle_row_layout.setSpacing(0)
        for mode_name in ("Full", "Custom"):
            btn = QtWidgets.QPushButton(mode_name)
            btn.setProperty("class", "amNavTabActive" if mode_name == self.mode else "amNavTab")
            btn.setCursor(QtCore.Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, m=mode_name: self._on_mode_clicked(m))
            toggle_row_layout.addWidget(btn)
        self.col2_layout.addWidget(toggle_row)

        if self.mode == "Full":
            info = QtWidgets.QLabel(
                f'{len(self.manifest.get("assets", []))} asset(s), '
                f'{len(self.manifest.get("shots", []))} shot(s) in this package.\n\n'
                'Everything will be staged for import.'
            )
            info.setWordWrap(True)
            info.setStyleSheet(f"color:{AM_TOKENS['text_muted_alt']}; font-size:10.5px; padding:10px;")
            self.col2_layout.addWidget(info)
            self.col2_layout.addStretch(1)
            self._stage_full()
            return

        # Custom mode — same Assets/Shots drill-down pattern as Export,
        # color-coded against what already exists at the destination.
        tab_row = QtWidgets.QWidget()
        tab_row_layout = QtWidgets.QHBoxLayout(tab_row)
        tab_row_layout.setContentsMargins(0, 0, 0, 0)
        tab_row_layout.setSpacing(0)
        for tab_name in ("Assets", "Shots"):
            btn = QtWidgets.QPushButton(tab_name)
            btn.setProperty("class", "amNavTabActive" if tab_name == self.nav_tab else "amNavTab")
            btn.setCursor(QtCore.Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, t=tab_name: self._on_tab_clicked(t))
            tab_row_layout.addWidget(btn)
        self.col2_layout.addWidget(tab_row)

        self.browse_header = QtWidgets.QLabel()
        self.browse_header.setProperty("class", "amSectionHeader")
        self.col2_layout.addWidget(self.browse_header)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        list_widget = QtWidgets.QWidget()
        self.browse_list_layout = QtWidgets.QVBoxLayout(list_widget)
        self.browse_list_layout.setContentsMargins(4, 4, 4, 4)
        self.browse_list_layout.setSpacing(1)
        self.browse_list_layout.addStretch(1)
        scroll.setWidget(list_widget)
        self.col2_layout.addWidget(scroll, 1)

        self._refresh_browse_list()

    def _on_mode_clicked(self, mode_name):
        self.mode = mode_name
        self.staged = {}
        self._build_column2()
        self._refresh_staged_list()

    def _on_tab_clicked(self, tab_name):
        self.nav_tab = tab_name
        self.asset_type = None
        self._refresh_browse_list()

    def _clear_browse_rows(self):
        while self.browse_list_layout.count() > 1:
            item = self.browse_list_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    # ---- diff coloring against the destination project ----

    def _asset_diff(self, asset):
        asset_name = asset.get("asset_name")
        asset_type = asset.get("asset_type")
        tasks = asset.get("tasks") or []
        local_dir = os.path.join(self.project_path, "assets", asset_type or "", asset_name or "")
        exists_locally = os.path.isdir(local_dir)
        if not exists_locally:
            return "new"
        missing = [t for t in tasks if not os.path.isdir(os.path.join(local_dir, t))]
        return "partial" if missing else "match"

    def _shot_diff(self, shot):
        shot_name = shot.get("shot_name")
        tasks = shot.get("tasks") or []
        local_dir = os.path.join(self.project_path, "shots", shot_name or "")
        exists_locally = os.path.isdir(local_dir)
        if not exists_locally:
            return "new"
        missing = [t for t in tasks if not os.path.isdir(os.path.join(local_dir, t))]
        return "partial" if missing else "match"

    def _refresh_browse_list(self):
        self._clear_browse_rows()

        if self.nav_tab == "Shots":
            self.browse_header.setText("Shots")
            for shot in self.manifest.get("shots", []):
                shot_name = shot.get("shot_name")
                if not shot_name:
                    continue
                diff = self._shot_diff(shot)
                row = _AssetManagerBrowseRow(shot_name, self._diff_sub_label(diff), has_add=True)
                self._tint_row(row, diff)
                row.add_clicked.connect(lambda s=shot: self._stage_single_shot(s))
                self.browse_list_layout.insertWidget(self.browse_list_layout.count() - 1, row)
            return

        assets_by_type = {}
        for asset in self.manifest.get("assets", []):
            assets_by_type.setdefault(asset.get("asset_type"), []).append(asset)

        if self.asset_type is None:
            self.browse_header.setText("Assets")
            for type_name in STANDARD_ASSET_TYPES:
                count = len(assets_by_type.get(type_name, []))
                if count == 0:
                    continue
                row = _AssetManagerBrowseRow(type_name.capitalize(), f"{count} asset{'s' if count != 1 else ''}", has_chevron=True)
                row.clicked.connect(lambda t=type_name: self._drill_into_type(t))
                self.browse_list_layout.insertWidget(self.browse_list_layout.count() - 1, row)
        else:
            self.browse_header.setText(self.asset_type.capitalize())
            for asset in assets_by_type.get(self.asset_type, []):
                asset_name = asset.get("asset_name")
                diff = self._asset_diff(asset)
                row = _AssetManagerBrowseRow(asset_name, self._diff_sub_label(diff), has_add=True)
                self._tint_row(row, diff)
                row.add_clicked.connect(lambda a=asset: self._stage_single_asset(a))
                self.browse_list_layout.insertWidget(self.browse_list_layout.count() - 1, row)

    @staticmethod
    def _diff_sub_label(diff):
        return {"new": "New", "partial": "Some tasks missing locally", "match": "Already matches"}[diff]

    @staticmethod
    def _tint_row(row, diff):
        if diff == "new":
            row.setStyleSheet(f"background:{AM_TOKENS['red_bg']};")
        elif diff == "partial":
            row.setStyleSheet(f"background:{AM_TOKENS['yellow_bg']};")

    def _drill_into_type(self, type_name):
        self.asset_type = type_name
        self._refresh_browse_list()

    # ---- staging ----

    def _stage_single_asset(self, asset):
        self._stage("asset", asset.get("asset_name"), asset)

    def _stage_single_shot(self, shot):
        self._stage("shot", shot.get("shot_name"), shot)

    def _stage_full(self):
        self._stage_many(
            [("asset", a.get("asset_name"), a) for a in self.manifest.get("assets", [])]
            + [("shot", s.get("shot_name"), s) for s in self.manifest.get("shots", [])]
        )

    def _on_import(self):
        if not self.staged:
            cmds.warning("Stage at least one asset or shot first.")
            return

        if not self.already_existed:
            build_project_skeleton(self.project_path)

        assets = [entry for (kind, _name), entry in self.staged.items() if kind == "asset"]
        shots = [entry for (kind, _name), entry in self.staged.items() if kind == "shot"]

        _apply_pipeline_package_settings(self.manifest)
        asset_lines, shot_lines = _build_pipeline_package_items(self.project_path, assets, shots)
        switch_to_project(self.project_path)

        self.close()
        _show_pipeline_package_import_summary(
            self.project_path, self.manifest.get("project_name"), self.already_existed, asset_lines, shot_lines
        )


# Groups Setup Scene creates, per asset task — model/rig/lookdev only (no
# rollout menu; the task is read from the scene's save location instead).
SETUP_SCENE_GROUPS = {
    "model": ("OBJ", "IGNORE"),
    "rig": ("rigRoot", "IGNORE"),
    "lookdev": ("OBJ", "IGNORE"),
}


def _prompt_setup_scene_task_choice():
    """
    2.31.14: Todd — "if it cannot tell what context the scene is in, ie..
    the scene hasnt been saved yet, then it should pop up a box that
    asks, model, rig, lookdev rather than waiting for the scene to be
    saved first. if the tool knows what context, then it doesnt need the
    popup." Same confirmDialog pattern as prompt_asset_type_choice.
    Returns "model"/"rig"/"lookdev", or None if cancelled.
    """
    result = cmds.confirmDialog(
        title="Setup Scene",
        message="This scene hasn't been saved yet, so its task can't be read from a file path.\n\nWhich task is this scene for?",
        button=["Model", "Rig", "Lookdev", "Cancel"],
        defaultButton="Model",
        cancelButton="Cancel",
        dismissString="Cancel",
    )
    if result == "Cancel":
        return None
    return result.lower()


def setup_scene(*_args):
    """
    Create the standard empty groups for whichever asset task the current
    scene is saved in — no rollout, the task is read straight from the
    scene's save location via _task_name_from_scene_path. Warns and does
    nothing for scenes SAVED somewhere Setup Scene doesn't recognize
    (fx/texture task folder, or outside the project — fx and texture have
    no defined group set, and this deliberately doesn't second-guess a
    real save location by popping up a picker over it).

    2.31.14: an UNSAVED scene (no save path at all — genuinely no context
    to read) no longer just warns and stops. Instead it asks directly via
    _prompt_setup_scene_task_choice (Model/Rig/Lookdev/Cancel) and creates
    that task's groups right away — group creation itself doesn't need a
    saved scene, only the task lookup did. This is deliberately scoped to
    the "no save path at all" case only, per Todd — a scene saved
    somewhere Setup Scene just doesn't recognize keeps the original
    warning below, since that's a real wrong-location problem, not an
    unknown-context one.
    """
    scene_path = cmds.file(query=True, sceneName=True)
    if not scene_path:
        task_name = _prompt_setup_scene_task_choice()
        if not task_name:
            return
        groups = SETUP_SCENE_GROUPS[task_name]
    else:
        task_name = _task_name_from_scene_path(scene_path)
        groups = SETUP_SCENE_GROUPS.get(task_name)
        if not groups:
            cmds.warning("Setup Scene only works for scenes saved in a Model, Rig, or Lookdev task folder.")
            return

    created = [name for name in groups if not cmds.objExists(name)]
    for name in created:
        cmds.group(empty=True, name=name)

    if created:
        print(f"Setup Scene ({task_name}): created {', '.join(created)}.")
    else:
        print(f"Setup Scene ({task_name}): groups already exist, nothing to do.")


def publish_scene(*_args):
    """
    Publish the current scene:
      1. Version it up in place (like Increment and Save, staying in
         work/maya/) — unchanged from before.
      2. Export SELECTED only — just the task's designated group (OBJ for
         model/lookdev, rigRoot for rig; same group Setup Scene creates,
         see SETUP_SCENE_GROUPS) — into output/<subfolder>/ under the same
         filename/version as the work file. The IGNORE group sits outside
         that hierarchy as a sibling, so Export Selected naturally leaves
         it out — nothing extra needed to exclude it.

    PUBLISH_OUTPUT_SUBFOLDER maps model/lookdev -> "geo", rig -> "rig".
    Only works for scenes saved in a Model, Rig, or Lookdev task folder —
    fx and texture aren't published. Aborts before touching anything
    (no version-up, no save) if the task's group doesn't exist yet — that
    means Setup Scene was never run for this scene.

    This is also the reason Asset Manager now reads model/rig/lookdev from
    output/<subfolder> instead of work/maya (asset_task_source_dir) — so
    it only ever offers versions that have actually been published.
    """
    scene_path = cmds.file(query=True, sceneName=True)
    if not scene_path:
        cmds.warning("Save the scene into a Model, Rig, or Lookdev task folder first.")
        return

    task_name = _task_name_from_scene_path(scene_path)
    subfolder = PUBLISH_OUTPUT_SUBFOLDER.get(task_name)
    if not subfolder:
        cmds.warning("Publish only works for scenes saved in a Model, Rig, or Lookdev task folder.")
        return

    export_group = SETUP_SCENE_GROUPS[task_name][0]  # "OBJ" for model/lookdev, "rigRoot" for rig
    if not cmds.objExists(export_group):
        # 2.31.4: Todd wanted this to actually stop and get his attention
        # instead of a Script Editor warning that's easy to miss.
        cmds.confirmDialog(
            title="Setup Scene Required",
            message=f"Can't publish — the {export_group} group was not found.\n\nPlease run Setup Scene first.",
            button=["OK"],
        )
        return

    work_dir = os.path.dirname(scene_path)  # .../<task>/work/maya/scenes (or maya/ for pre-2.31.4 files)
    filename = os.path.basename(scene_path)
    match = VERSIONED_FILE_PATTERN.match(filename)
    if not match:
        cmds.warning(
            f'"{filename}" doesn\'t match the <name>.vNNN.ext naming convention this pipeline uses — '
            "save it through Setup As / the normal create flow first."
        )
        return
    stub, ext = match.group(1), match.group(3)
    file_type = "mayaAscii" if ext.lower() == "ma" else "mayaBinary"

    next_version = get_next_asset_version(work_dir, stub)
    new_filename = f"{stub}.v{next_version:03d}.{ext}"
    new_path = os.path.join(work_dir, new_filename)

    cmds.file(rename=new_path)
    align_maya_project()
    cmds.file(save=True, type=file_type)
    cmds.file(modified=False)

    # 2.31.6: was `os.path.dirname(os.path.dirname(work_dir))`, which
    # assumed work_dir was always exactly .../<task>/work/maya (two levels
    # under <task>) — true before 2.31.4, but work_dir is now one level
    # deeper (.../work/maya/scenes) for anything saved since, which sent
    # published output to .../<task>/work/output/<type> instead of
    # .../<task>/output/<type>. Resolve the real "maya" folder first (works
    # for both the old flat location and the new scenes/ one) and walk up
    # from THAT instead, so publish output is unaffected either way.
    maya_dir = _maya_folder_from_scene_path(scene_path)
    task_dir = os.path.dirname(os.path.dirname(maya_dir))  # .../<task>/work/maya -> .../<task>
    output_dir = os.path.join(task_dir, "output", subfolder)
    os.makedirs(output_dir, exist_ok=True)
    dest_path = os.path.join(output_dir, new_filename)

    previous_selection = cmds.ls(selection=True) or []
    try:
        cmds.select(export_group, replace=True)
        cmds.file(dest_path, exportSelected=True, type=file_type, force=True)
    except Exception as e:
        cmds.warning(f"Saved work file, but could not export {export_group} to {dest_path}: {e}")
        return
    finally:
        if previous_selection:
            cmds.select(previous_selection, replace=True)
        else:
            cmds.select(clear=True)

    print(f"Published: {new_path} -> {dest_path} (exported {export_group})")
    cmds.confirmDialog(
        title="Scene Published",
        message=f"Saved: {new_filename}\nPublished {export_group} to:\n{output_dir}",
        button=["OK"],
    )


def _shot_anim_context_from_scene_path(scene_path):
    """
    Given a scene path, return (shot_name, project_path) if it sits at the
    standard shots/<shot>/anim/work/maya/<file> location (see
    SHOT_TASK_MAYA_SUBPATH — anim is work/maya same as every other task),
    else (None, None). Used by Export Cache to know which shot's
    output/cache folder to write into, purely from where the scene is
    saved — same pattern as _task_name_from_scene_path/Setup Scene/Publish.
    """
    task_name = _task_name_from_scene_path(scene_path)
    if task_name != "anim":
        return None, None

    # scene_path: .../shots/<shot>/anim/work/maya(/scenes)/<file>
    maya_dir = _maya_folder_from_scene_path(scene_path)
    work_dir = os.path.dirname(maya_dir)
    task_dir = os.path.dirname(work_dir)  # .../shots/<shot>/anim
    shot_dir = os.path.dirname(task_dir)  # .../shots/<shot>
    shots_dir = os.path.dirname(shot_dir)  # .../shots
    if os.path.basename(shots_dir) != "shots":
        return None, None

    project_path = os.path.dirname(shots_dir)
    return os.path.basename(shot_dir), project_path


EXPORT_CACHE_WINDOW = "exportCacheWindow"


_CACHE_NAME_NAMESPACE_PATTERN = re.compile(
    rf"^(.+)_(?:{'|'.join(re.escape(t) for t in ASSET_TASK_SUFFIXES)})_v\d+$", re.IGNORECASE
)


def _cache_name_for_selected_node(node):
    """
    Best-effort ASSET name for a selected node, used to name its Export
    Cache file — Todd's explicit ask (2.21.2): the cache should be named
    after the asset being exported, not whatever group node happened to
    be selected (e.g. selecting a referenced rig's "OBJ" group should
    still produce "georgeMichael_anim.v001.abc", not "OBJ_anim.v001.abc").

    If the node sits under a reference namespace matching the pipeline's
    "<asset>_<task>_vNNN" convention (see namespace_for_versioned_file,
    e.g. "georgeMichael_rig_v007:OBJ") the task+version suffix is
    stripped to recover the plain asset name ("georgeMichael"). Falls
    back to the node's own bare short name when there's no namespace, or
    the namespace doesn't match that pattern (e.g. a plain unreferenced
    scene object like "camera" or "car").
    """
    short_name = node.split("|")[-1]
    parts = short_name.split(":")
    if len(parts) < 2:
        return short_name  # no namespace at all

    namespace = parts[-2]  # the namespace immediately containing this node
    match = _CACHE_NAME_NAMESPACE_PATTERN.match(namespace)
    return match.group(1) if match else namespace


def _resolve_export_cache_root(node):
    """
    2.31.13: Todd — "when caching, no matter what is selected, the tool
    should always only cache the OBJ node.. not the rigRoot or the joint
    node." Export Cache used to export exactly whatever was selected as
    the AbcExport -root — fine for a plain unreferenced object, but wrong
    for a rig: selecting rigRoot (or a joint under it, e.g. picking one
    control to key on) used to cache the joint hierarchy itself instead
    of the skinned geometry, which is what actually needs to be an
    animated Alembic cache (and what _attach_cache_to_node later merges
    onto a Shade asset's own OBJ node — a joint-hierarchy cache wouldn't
    even attach correctly there).

    Given any selected node, finds its immediate reference namespace
    (same "second-to-last piped segment" convention used by
    _cache_name_for_selected_node and _shade_asset_namespace_and_label)
    and looks for "<namespace>:OBJ" as a sibling within that same
    namespace — this matches Setup Scene's own convention
    (SETUP_SCENE_GROUPS: model/lookdev -> "OBJ", rig -> "rigRoot", both
    siblings under the same asset namespace). Returns that OBJ node's
    long path if found and uniquely resolvable.

    Falls back to the original node unchanged if there's no namespace at
    all (a plain unreferenced object like a camera or prop — nothing to
    resolve), or "<namespace>:OBJ" doesn't exist/isn't unique — so
    non-rig selections keep working exactly as before.
    """
    short_name = node.split("|")[-1]
    parts = short_name.split(":")
    if len(parts) < 2:
        return node  # no namespace at all — nothing to resolve, cache it as-is

    namespace = parts[-2]
    candidate = f"{namespace}:OBJ"
    if not cmds.objExists(candidate):
        return node
    resolved = cmds.ls(candidate, long=True) or []
    return resolved[0] if len(resolved) == 1 else node


def export_selection_to_cache(*_args):
    """
    "Export Cache" — context-aware Alembic export. Reads which shot the
    current scene belongs to straight from where it's saved (must be a
    shot's Anim task folder, work/maya) via _shot_anim_context_from_scene_path
    — same "no picking, just read it from the save location" pattern as
    Setup Scene / Publish — and always writes into that shot's
    shots/<shot>/anim/output/cache/ folder (get_shot_cache_dir).

    Writes ONE independently-versioned .abc file PER TOP-LEVEL SELECTED
    OBJECT — named after the ASSET, not the shot and not necessarily the
    selected node itself (see _cache_name_for_selected_node) — e.g.
    selecting georgeMichael's referenced "OBJ" group, camera, hat, and
    car and exporting writes georgeMichael_anim.v001.abc,
    camera_anim.v001.abc, hat_anim.v001.abc, and car_anim.v001.abc
    (get_next_cache_version per object stub), so Asset Manager's Cache
    type (which lists cache name stubs per shot via get_shot_cache_names)
    can offer each object's cache independently. Per-object naming was
    Todd's explicit ask (2.20.4) — this replaced the original 2.20.0
    behavior of one combined <shot>_anim.vNNN.abc file for the whole
    selection. Naming off the ASSET rather than the raw selected node
    name was a follow-up fix (2.21.2) — selecting a referenced rig's
    "OBJ" group used to produce "OBJ_anim.v001.abc" instead of
    "georgeMichael_anim.v001.abc".

    This is a small custom frame-range option window rather than Maya's
    built-in Cache > Alembic Cache > Export Selection to Alembic... option
    box — the built-in dialog's underlying MEL procedure name isn't
    reliably the same across Maya versions/plugin builds, so hooking into
    it directly risks breaking on Todd's Maya version. This does the same
    job (AbcExport per top-level selected node, frame-ranged) but the
    output path is fixed to the context-aware cache location instead of a
    user-chosen one, per Todd's ask.

    2.31.13: every selected node is first resolved to its asset's OBJ
    node via _resolve_export_cache_root (see that function's docstring)
    before anything else — naming, versioning, and the actual export all
    operate on the RESOLVED node, not the raw selection. Two originally-
    selected nodes that resolve to the same OBJ (e.g. a joint and a
    control on the same rig) are de-duplicated so that asset is only
    exported once, not once per originally-selected node.
    """
    raw_selection = cmds.ls(selection=True, long=True) or []
    if not raw_selection:
        cmds.warning("Select the node(s) to cache first.")
        return

    selection = []
    seen_resolved = set()
    for node in raw_selection:
        resolved = _resolve_export_cache_root(node)
        if resolved in seen_resolved:
            continue
        seen_resolved.add(resolved)
        selection.append(resolved)

    scene_path = cmds.file(query=True, sceneName=True)
    if not scene_path:
        cmds.warning("Save the scene into a shot's Anim task folder first.")
        return

    shot_name, project_path = _shot_anim_context_from_scene_path(scene_path)
    if not shot_name:
        cmds.warning("Export Cache only works for scenes saved in a shot's Anim task folder.")
        return

    cache_dir = get_shot_cache_dir(project_path, shot_name)

    # Precompute a filename per selected node up front (for the preview
    # list and the actual export). Two selected nodes can share a short
    # name (e.g. same object name under different groups/namespaces) — if
    # so, get_next_cache_version alone would hand out the same version to
    # both, so bump by how many times that stub has already appeared in
    # THIS batch.
    stub_counts = {}
    export_items = []  # list of (node, stub, filename, file_path)
    for node in selection:
        stub = f"{_cache_name_for_selected_node(node)}_anim"
        base_version = get_next_cache_version(cache_dir, stub)
        version = base_version + stub_counts.get(stub, 0)
        stub_counts[stub] = stub_counts.get(stub, 0) + 1
        filename = f"{stub}.v{version:03d}.abc"
        export_items.append((node, stub, filename, os.path.join(cache_dir, filename)))

    if cmds.window(EXPORT_CACHE_WINDOW, exists=True):
        cmds.deleteUI(EXPORT_CACHE_WINDOW)

    window = cmds.window(EXPORT_CACHE_WINDOW, title="Export Cache", sizeable=False, width=380)
    cmds.columnLayout(adjustableColumn=True, columnAlign="left", rowSpacing=6, columnOffset=("both", 12))

    cmds.text(label="")  # top spacer
    cmds.text(label="Export Cache to Alembic", font="boldLabelFont", align="left")
    cmds.separator(height=10, style="in")

    cmds.text(label=f"Shot: {shot_name}", align="left")
    cmds.text(label=f"Will write {len(export_items)} file(s) to: {cache_dir}", align="left")
    preview_text = "\n".join(filename for _node, _stub, filename, _path in export_items)
    cmds.scrollField(
        text=preview_text,
        editable=False,
        wordWrap=False,
        height=min(20 * len(export_items) + 10, 120),
    )

    cmds.separator(height=10, style="in")

    start_default = int(cmds.playbackOptions(query=True, minTime=True))
    end_default = int(cmds.playbackOptions(query=True, maxTime=True))

    cmds.rowLayout(numberOfColumns=2, columnWidth2=(90, 220), adjustableColumn=2)
    cmds.text(label="Frame Range")
    frame_range_field = cmds.intFieldGrp(numberOfFields=2, value1=start_default, value2=end_default)
    cmds.setParent("..")

    cmds.separator(height=10, style="in")

    def on_export(*_args):
        start_frame = cmds.intFieldGrp(frame_range_field, query=True, value1=True)
        end_frame = cmds.intFieldGrp(frame_range_field, query=True, value2=True)
        if end_frame < start_frame:
            cmds.warning("End frame must be >= start frame.")
            return

        os.makedirs(cache_dir, exist_ok=True)

        original_selection = cmds.ls(selection=True, long=True) or []
        succeeded = []
        failed = []
        try:
            for node, _stub, filename, file_path in export_items:
                # AbcExport's job string is parsed MEL-style, so backslashes
                # in a Windows path (e.g. "C:\Users\toddp\...") get read as
                # escape sequences (\t -> tab, etc.), silently corrupting the
                # -file path. AbcExport doesn't raise for this - it just
                # fails to write - so forward-slash the path before
                # embedding it in the job string.
                abc_file_path = file_path.replace("\\", "/")
                cmds.select(node, replace=True)
                job = (
                    f"-frameRange {start_frame} {end_frame} -uvWrite -worldSpace -writeVisibility "
                    f"-dataFormat ogawa -root \"{node}\" -file \"{abc_file_path}\""
                )
                try:
                    cmds.AbcExport(j=job)
                    succeeded.append(filename)
                    print(f"Exported cache: {file_path}")
                except Exception as e:
                    failed.append(filename)
                    cmds.warning(f"Could not export cache to {file_path}: {e}")
        finally:
            if original_selection:
                cmds.select(original_selection, replace=True)
            else:
                cmds.select(clear=True)

        cmds.deleteUI(window)
        if not succeeded:
            cmds.confirmDialog(title="Cache Export Failed", message="No cache files were written. Check the Script Editor for details.", button=["OK"])
            return

        message = f"Wrote {len(succeeded)} file(s) to:\n{cache_dir}\n\n" + "\n".join(succeeded)
        if failed:
            message += "\n\nFailed:\n" + "\n".join(failed)
        cmds.confirmDialog(title="Cache Exported", message=message, button=["OK"])

    cmds.columnLayout(adjustableColumn=True)
    cmds.rowLayout(numberOfColumns=3, columnWidth3=(10, 85, 85), adjustableColumn=1, columnAlign3=("left", "right", "right"))
    cmds.text(label="")
    cmds.button(label="Export", width=85, command=on_export)
    cmds.button(label="Cancel", width=85, command=lambda *a: cmds.deleteUI(window))
    cmds.setParent("..")
    cmds.setParent("..")

    cmds.text(label="")  # bottom spacer

    cmds.showWindow(window)


IMPORT_CACHES_WINDOW = "importCachesWindow"


def show_import_caches_window(*_args):
    """
    SUPERSEDED (2.24.0) — the "Import Caches" menu item now opens
    show_import_caches_panel()'s PySide panel instead, styled to match
    the Asset Manager panel. This cmds.window version is left fully
    intact/unwired, as a fallback/rollback (same pattern as
    show_asset_manager_window during the 2.23.0 Asset Manager overhaul).
    All of its logic (auto-match, Default Shader fallback, connect=-based
    attach) was carried over into the new panel unchanged.

    "Import Caches" — the streamlined counterpart to Export Cache. Where
    Add Asset's Cache flow (Shot / Cache Name / Ver) attaches ONE cache at
    a time and pops a separate shade-picker window per cache, this lists
    EVERY cache available for a picked shot as a table (one row per cache
    name — see get_shot_cache_names) and lets you set the Shade asset +
    version each one attaches to, then imports everything checked in a
    single pass. Todd's ask: "a window of all the caches in the scene and
    selecting the file they attach to.. something more streamlined."

    Deliberately a separate window/menu item rather than folded into Add
    Asset — Add Asset's one-thing-at-a-time flow (with its Type dropdown
    covering every asset task) is a different shape of tool than "attach
    N caches for this shot in one go", per Todd's explicit "could live
    separate from the add asset window."

    Shot is picked from a dropdown here (not read from the current
    scene's save path like Export Cache/Setup Scene/Publish) — Todd's
    explicit choice, so this works regardless of which scene is open, or
    with no scene saved at all.

    Each row's Shade Asset dropdown auto-matches by name when possible
    (cache "georgeMichael_anim" -> strip the "_anim" suffix -> if a
    published Shade asset is literally named "georgeMichael", pre-select
    it) — Todd's explicit ask, to cut clicks for the common case where
    cache and asset names line up. Falls back to the unpicked placeholder
    when there's no match, same as everywhere else in this file.

    The Shade Asset dropdown also offers a "Default Shader" entry (2.21.1,
    Todd's explicit ask: "add an option to apply a default shader to a
    cache with no matching shader (or if the user wants that)") — usable
    on ANY row, not just unmatched ones. Picking it skips the
    reference/OBJ/reparent dance entirely: the cache is imported standalone
    (no reparent target) and its shapes are force-assigned to
    initialShadingGroup (Maya's default lambert1 shading group) so the
    geo isn't left shaderless. Still opt-in per row, not automatic for
    unmatched caches — every dropdown in this window still forces an
    explicit pick (see IMPORT_CACHES_NAME_PLACEHOLDER), Default Shader is
    just one more explicit choice alongside every real Shade asset.

    The actual reference + AbcImport-merge logic is intentionally
    duplicated here rather than shared with show_cache_shade_picker_window
    — same three steps (reference the Shade asset, select its OBJ node,
    AbcImport connect onto it — see the 2.21.3 fix note on that function
    for why "connect", not "reparent"), but this version collects per-row
    successes/failures into one summary dialog instead of one dialog per
    cache. If that core logic ever needs changing, both places need it.
    """
    project_path = get_current_project()
    if not project_path:
        return

    if cmds.window(IMPORT_CACHES_WINDOW, exists=True):
        cmds.deleteUI(IMPORT_CACHES_WINDOW)

    window = cmds.window(IMPORT_CACHES_WINDOW, title="Import Caches", sizeable=True, width=560)
    main_column = cmds.columnLayout(adjustableColumn=True, columnAlign="left", rowSpacing=6, columnOffset=("both", 12))

    cmds.text(label="")  # top spacer
    cmds.text(label="Import Caches", font="boldLabelFont", align="left")
    cmds.text(
        label='Pick a shot, then a Shade asset + version for each cache to bring in ("Default Shader" for a plain import).',
        align="left",
        enable=False,
    )
    cmds.separator(height=10, style="in")

    IMPORT_CACHES_SHOT_PLACEHOLDER = "Shot"
    IMPORT_CACHES_NAME_PLACEHOLDER = "Name"
    IMPORT_CACHES_VER_PLACEHOLDER = "Ver"
    IMPORT_CACHES_DEFAULT_SHADER_LABEL = "Default Shader"

    cmds.rowLayout(numberOfColumns=2, columnAttach2=("left", "left"), columnOffset2=(0, 8))
    shot_dropdown = cmds.optionMenu(width=160)
    cmds.setParent("..")

    cmds.separator(height=10, style="in")

    cmds.rowLayout(
        numberOfColumns=6,
        columnWidth6=(24, 140, 55, 20, 150, 55),
        columnAlign6=("left", "left", "left", "left", "left", "left"),
    )
    cmds.text(label="")
    cmds.text(label="Cache", font="boldLabelFont", align="left")
    cmds.text(label="Ver", font="boldLabelFont", align="left")
    cmds.text(label="")
    cmds.text(label="Shade Asset", font="boldLabelFont", align="left")
    cmds.text(label="Ver", font="boldLabelFont", align="left")
    cmds.setParent("..")

    rows_scroll = cmds.scrollLayout(height=220, horizontalScrollBarThickness=0, childResizable=True)
    rows_column = cmds.columnLayout(adjustableColumn=True, columnAlign="left", rowSpacing=2)
    cmds.setParent("..")  # out of rows_column
    cmds.setParent("..")  # out of rows_scroll

    cmds.separator(height=10, style="in")

    row_widgets = []  # list of dicts, one per cache row — see refresh_rows

    def refresh_rows(*_args):
        for child in cmds.columnLayout(rows_column, query=True, childArray=True) or []:
            cmds.deleteUI(child)
        row_widgets.clear()

        shot_name = cmds.optionMenu(shot_dropdown, query=True, value=True)
        cmds.setParent(rows_column)

        if not shot_name or shot_name == IMPORT_CACHES_SHOT_PLACEHOLDER:
            cmds.text(label="Select a shot to see its caches.", align="left", enable=False)
            return

        cache_names = get_shot_cache_names(project_path, shot_name)
        if not cache_names:
            cmds.text(label=f'No caches found for shot "{shot_name}".', align="left", enable=False)
            return

        shade_assets = list_assets_with_task(project_path, "lookdev")

        for cache_name in cache_names:
            cmds.setParent(rows_column)
            cmds.rowLayout(
                numberOfColumns=6,
                columnWidth6=(24, 140, 55, 20, 150, 55),
                columnAlign6=("left", "left", "left", "left", "left", "left"),
            )

            checkbox = cmds.checkBox(label="", value=True)
            cmds.text(label=cache_name, align="left")

            cache_ver_dropdown = cmds.optionMenu(width=55)
            cache_ver_lookup = {}
            cache_versions = get_shot_cache_versions(project_path, shot_name, cache_name)  # newest first
            for filename in cache_versions:
                match = CACHE_VERSIONED_FILE_PATTERN.match(filename)
                label = f"v{match.group(2)}" if match else filename
                cache_ver_lookup[label] = filename
                cmds.menuItem(label=label, parent=cache_ver_dropdown)
            # optionMenu defaults to the first item added, which is already
            # the latest version since cache_versions is newest-first — no
            # placeholder needed here, get_shot_cache_names guarantees at
            # least one file exists for every stub it returns.

            cmds.text(label="")  # (2.22.6) spacer so Shade Asset/Ver sit apart from the cache columns

            asset_dropdown = cmds.optionMenu(width=150)
            cmds.menuItem(label=IMPORT_CACHES_NAME_PLACEHOLDER, parent=asset_dropdown)
            cmds.menuItem(label=IMPORT_CACHES_DEFAULT_SHADER_LABEL, parent=asset_dropdown)
            for asset_name in shade_assets:
                cmds.menuItem(label=asset_name, parent=asset_dropdown)

            # Auto-match: "georgeMichael_anim" -> "georgeMichael" -> exact
            # (case-insensitive) match against a published Shade asset name.
            guess = cache_name[:-5] if cache_name.lower().endswith("_anim") else cache_name
            matched_asset = next((a for a in shade_assets if a.lower() == guess.lower()), None)
            if matched_asset:
                cmds.optionMenu(asset_dropdown, edit=True, value=matched_asset)

            asset_ver_dropdown = cmds.optionMenu(width=55)
            asset_ver_lookup = {}

            def make_refresh_asset_versions(asset_dropdown=asset_dropdown, asset_ver_dropdown=asset_ver_dropdown, asset_ver_lookup=asset_ver_lookup):
                def _refresh(*_args):
                    for item in cmds.optionMenu(asset_ver_dropdown, query=True, itemListLong=True) or []:
                        cmds.deleteUI(item)
                    asset_ver_lookup.clear()

                    asset_name = cmds.optionMenu(asset_dropdown, query=True, value=True)
                    if asset_name == IMPORT_CACHES_DEFAULT_SHADER_LABEL:
                        # No version to pick for the default shader — disable
                        # rather than leave a meaningless dropdown active.
                        cmds.menuItem(label="—", parent=asset_ver_dropdown)
                        cmds.optionMenu(asset_ver_dropdown, edit=True, enable=False)
                        return
                    cmds.optionMenu(asset_ver_dropdown, edit=True, enable=True)
                    cmds.menuItem(label=IMPORT_CACHES_VER_PLACEHOLDER, parent=asset_ver_dropdown)

                    if asset_name == IMPORT_CACHES_NAME_PLACEHOLDER:
                        return
                    filenames = get_asset_task_versions(project_path, asset_name, "lookdev")
                    for filename in filenames:
                        match = VERSIONED_FILE_PATTERN.match(filename)
                        label = f"v{match.group(2)}" if match else filename
                        asset_ver_lookup[label] = filename
                        cmds.menuItem(label=label, parent=asset_ver_dropdown)
                    if filenames:
                        # Pre-select latest, same "Cache" exception as Add
                        # Asset's Ver dropdown (2.20.4) — every dropdown here
                        # otherwise forces an explicit pick.
                        latest_match = VERSIONED_FILE_PATTERN.match(filenames[0])
                        latest_label = f"v{latest_match.group(2)}" if latest_match else filenames[0]
                        cmds.optionMenu(asset_ver_dropdown, edit=True, value=latest_label)

                return _refresh

            refresh_asset_versions = make_refresh_asset_versions()
            cmds.optionMenu(asset_dropdown, edit=True, changeCommand=refresh_asset_versions)
            refresh_asset_versions()  # also fills in the auto-matched row's version

            cmds.setParent("..")  # close this row's rowLayout

            row_widgets.append({
                "cache_name": cache_name,
                "checkbox": checkbox,
                "cache_ver_dropdown": cache_ver_dropdown,
                "cache_ver_lookup": cache_ver_lookup,
                "asset_dropdown": asset_dropdown,
                "asset_ver_dropdown": asset_ver_dropdown,
                "asset_ver_lookup": asset_ver_lookup,
            })

    cmds.menuItem(label=IMPORT_CACHES_SHOT_PLACEHOLDER, parent=shot_dropdown)
    for shot_name in list_existing_shots(project_path):
        cmds.menuItem(label=shot_name, parent=shot_dropdown)
    cmds.optionMenu(shot_dropdown, edit=True, changeCommand=refresh_rows)
    refresh_rows()
    # refresh_rows() ends with the UI "current parent" pointed at rows_column
    # (it has to, to add rows/placeholder text there) — reset it back to the
    # window's main column before building anything else, or subsequent
    # controls (the Import/Cancel buttons below) silently end up nested
    # inside the small fixed-height rows scrollLayout instead of the window.
    cmds.setParent(main_column)

    def do_import_checked(*_args):
        shot_name = cmds.optionMenu(shot_dropdown, query=True, value=True)
        if not shot_name or shot_name == IMPORT_CACHES_SHOT_PLACEHOLDER:
            cmds.warning("Select a shot first.")
            return
        if not row_widgets:
            cmds.warning("No caches to import.")
            return

        cache_dir = get_shot_cache_dir(project_path, shot_name)
        succeeded = []
        skipped_unset = []
        failed = []
        any_checked = False

        for row in row_widgets:
            if not cmds.checkBox(row["checkbox"], query=True, value=True):
                continue
            any_checked = True

            cache_label = cmds.optionMenu(row["cache_ver_dropdown"], query=True, value=True)
            cache_filename = row["cache_ver_lookup"].get(cache_label)
            asset_name = cmds.optionMenu(row["asset_dropdown"], query=True, value=True)

            if asset_name == IMPORT_CACHES_NAME_PLACEHOLDER or not cache_filename:
                skipped_unset.append(row["cache_name"])
                continue

            cache_file_path = os.path.join(cache_dir, cache_filename)

            if asset_name == IMPORT_CACHES_DEFAULT_SHADER_LABEL:
                # No Shade asset to reference/reparent onto — import the
                # cache standalone and force-assign Maya's default shading
                # group (initialShadingGroup, i.e. lambert1) so the geo
                # isn't left shaderless. New top-level nodes are found by
                # diffing cmds.ls(assemblies=True) before/after the import,
                # since AbcImport doesn't hand back the nodes it created.
                before_nodes = set(cmds.ls(assemblies=True, long=True) or [])
                try:
                    cmds.AbcImport(cache_file_path, mode="import")
                except Exception as e:
                    failed.append(f'{row["cache_name"]}: could not import cache: {e}')
                    continue
                after_nodes = set(cmds.ls(assemblies=True, long=True) or [])
                new_nodes = list(after_nodes - before_nodes)
                shapes = cmds.listRelatives(new_nodes, allDescendents=True, type="shape", fullPath=True) or [] if new_nodes else []
                if shapes:
                    cmds.sets(shapes, edit=True, forceElement="initialShadingGroup")
                succeeded.append(f'{row["cache_name"]} -> default shader ({len(new_nodes)} node(s))')
                continue

            asset_ver_label = cmds.optionMenu(row["asset_ver_dropdown"], query=True, value=True)
            asset_filename = row["asset_ver_lookup"].get(asset_ver_label)
            if not asset_filename:
                skipped_unset.append(row["cache_name"])
                continue

            asset_dir = find_asset_folder(project_path, asset_name)
            if not asset_dir:
                failed.append(f'{row["cache_name"]}: could not find asset folder for "{asset_name}".')
                continue

            shade_file_path = os.path.join(asset_task_source_dir(asset_dir, "lookdev"), asset_filename)
            namespace = namespace_for_versioned_file(asset_filename)
            try:
                cmds.file(shade_file_path, reference=True, namespace=namespace)
            except Exception as e:
                failed.append(f'{row["cache_name"]}: could not reference {shade_file_path}: {e}')
                continue

            obj_node = f"{namespace}:OBJ"
            if not cmds.objExists(obj_node):
                failed.append(
                    f'{row["cache_name"]}: referenced "{asset_name}" but no "{obj_node}" group found — cache not imported.'
                )
                continue

            try:
                # connect=, not reparent= — see the 2.21.3 fix note in
                # show_cache_shade_picker_window's on_import for why.
                # 2.22.0: routed through the shared _attach_cache_to_node
                # helper + tagged via _tag_cache_attachment, so this
                # attachment shows up as its own row in Asset Manager and
                # can be versioned up from there.
                _attach_cache_to_node(cache_file_path, obj_node, asset_name=asset_name)
                _tag_cache_attachment(obj_node, shot_name, row["cache_name"])
            except Exception as e:
                failed.append(f'{row["cache_name"]}: referenced "{asset_name}" but could not import cache: {e}')
                continue

            succeeded.append(f'{row["cache_name"]} -> {asset_name} ({namespace}:OBJ)')

        if not any_checked:
            cmds.warning("Nothing checked to import.")
            return

        lines = []
        if succeeded:
            lines.append(f"Imported {len(succeeded)}:")
            lines.extend(succeeded)
        if skipped_unset:
            if lines:
                lines.append("")
            lines.append(
                "Skipped (pick a Shade asset + version, or Default Shader): " + ", ".join(skipped_unset)
            )
        if failed:
            if lines:
                lines.append("")
            lines.append("Failed:")
            lines.extend(failed)

        cmds.deleteUI(window)
        cmds.confirmDialog(title="Import Caches", message="\n".join(lines), button=["OK"])

    cmds.columnLayout(adjustableColumn=True)
    cmds.rowLayout(numberOfColumns=3, columnWidth3=(10, 110, 90), adjustableColumn=1, columnAlign3=("left", "right", "right"))
    cmds.text(label="")
    cmds.button(label="Import", width=110, command=do_import_checked)
    cmds.button(label="Cancel", width=90, command=lambda *a: cmds.deleteUI(window))
    cmds.setParent("..")
    cmds.setParent("..")

    cmds.text(label="")  # bottom spacer

    cmds.showWindow(window)


def _save_scene_as(folder_path, filename_stub):
    """Save the current scene as <filename_stub>.vNNN.ma, auto-incrementing the version number for that file."""
    if not os.path.isdir(folder_path):
        os.makedirs(folder_path)

    version = get_next_asset_version(folder_path, filename_stub)
    file_path = os.path.join(folder_path, f"{filename_stub}.v{version:03d}.ma")
    cmds.file(rename=file_path)
    align_maya_project()
    cmds.file(save=True, type="mayaAscii")
    cmds.file(modified=False)

    print(f"Saved scene: {file_path}")
    cmds.confirmDialog(title="Scene Saved", message=f"Saved to:\n{file_path}", button=["OK"])
    return file_path


def create_new_asset_model():
    """Model task: prompt for asset type + name, then save into assets/<type>/<name>/model/work/maya/<name>_model.vNNN.ma."""
    project_path = get_current_project()
    if not project_path:
        return

    asset_type = prompt_asset_type_choice()
    if not asset_type:
        return

    asset_name = _prompt_for_name("New Model Asset", "Asset Name:")
    if not asset_name:
        return

    asset_dir = os.path.join(project_path, "assets", asset_type, asset_name)
    build_asset_task_structure(asset_dir)

    dest_dir = asset_task_scenes_dir(asset_dir, "model")
    _save_scene_as(dest_dir, f"{asset_name}_model")


def create_new_asset_custom():
    """Custom task: prompt for a brand-new type + name, then save into assets/<type>/<name>/model/work/maya/<name>_model.vNNN.ma."""
    project_path = get_current_project()
    if not project_path:
        return

    asset_type = _prompt_for_name("Custom Asset Type", "Asset Type Name:")
    if not asset_type:
        return

    asset_name = _prompt_for_name("New Asset", "Asset Name:")
    if not asset_name:
        return

    asset_dir = os.path.join(project_path, "assets", asset_type, asset_name)
    build_asset_task_structure(asset_dir)

    dest_dir = asset_task_scenes_dir(asset_dir, "model")
    _save_scene_as(dest_dir, f"{asset_name}_model")


def create_new_asset_task(task_name):
    """
    Rig / Lookdev / FX: prompt for the asset name only, search existing asset
    type folders for a match, then save into it. Requires the asset to
    already exist (created via Model or Custom first).
    """
    project_path = get_current_project()
    if not project_path:
        return

    asset_name = _prompt_for_name(f"New {task_name.capitalize()} Scene", "Asset Name:")
    if not asset_name:
        return

    asset_dir = find_asset_folder(project_path, asset_name)
    if not asset_dir:
        cmds.warning(
            f'No existing asset folder found named "{asset_name}". '
            'Use "Model" or "Custom" to create it first.'
        )
        return

    build_asset_task_structure(asset_dir)  # ensure all task folders exist, in case any are missing

    dest_dir = asset_task_scenes_dir(asset_dir, task_name)
    _save_scene_as(dest_dir, f"{asset_name}_{task_name}")



def create_new_shot_task(task_name):
    """
    Anim / FX / Lighting: prompt for a shot number, create the shot folder
    (with its full standard task/software structure) if needed, then report
    the specific task folder to use. Does not save the scene.
    """
    prefix = get_shot_prefix()
    project_path = get_current_project()
    if not prefix or not project_path:
        return

    number = _prompt_for_int(f"New {task_name.capitalize()} Shot", "Shot Number (e.g. 10):")
    if number is None:
        return

    scenes_dir = get_scenes_directory(project_path)
    shot_name = format_shot_name(prefix, number)
    shot_path = os.path.join(scenes_dir, shot_name)
    os.makedirs(shot_path, exist_ok=True)
    build_shot_task_structure(shot_path)

    task_path = os.path.join(shot_path, task_name)

    print(f"Shot folder ready: {shot_path}")
    print(f"  {task_name.capitalize()} folder: {task_path}")
    cmds.confirmDialog(
        title="Shot Folder Ready",
        message=f"{task_name.capitalize()} folder ready at:\n{task_path}",
        button=["OK"],
    )


SAVE_AS_WINDOW = "saveAsWindow"

# Which subfolder path (under a shot's task folder) holds Maya scene files,
# per task — matches the maya/scenes subfolder location within
# SHOT_TASK_STRUCTURE. Includes the "scenes" leaf as of 2.31.4 — see
# asset_task_scenes_dir's docstring for why.
SHOT_TASK_MAYA_SUBPATH = {
    "previs": ["work", "maya", "scenes"],
    "anim": ["work", "maya", "scenes"],
    "lighting": ["work", "maya", "scenes"],
    "fx": ["work", "maya", "scenes"],
}


def list_existing_shots(project_path):
    """Return the names of existing shot folders under <project>/shots, sorted."""
    shots_dir = os.path.join(project_path, "shots")
    if not os.path.isdir(shots_dir):
        return []
    return sorted(
        name for name in os.listdir(shots_dir)
        if os.path.isdir(os.path.join(shots_dir, name))
    )


def get_latest_versioned_file(folder_path, filename_stub):
    """Return (filename, version) of the highest-numbered <stub>.vNNN.ext file in folder_path, or (None, 0)."""
    highest_version = 0
    highest_file = None
    if os.path.isdir(folder_path):
        pattern = re.compile(rf"^{re.escape(filename_stub)}\.v(\d+)\.(ma|mb)$", re.IGNORECASE)
        for name in os.listdir(folder_path):
            match = pattern.match(name)
            if match:
                version = int(match.group(1))
                if version > highest_version:
                    highest_version = version
                    highest_file = name
    return highest_file, highest_version


def show_save_as_window():
    """
    Option-box style window for Save As, consolidating the old Asset/Shot
    flyout submenus into one dialog with a top-level Asset/Shot toggle
    that determines which section (and the Create button) is active.

    Asset Name is a dropdown of EXISTING asset folders only (no free-text
    entry, no "create a new asset" path here anymore) — per Todd: typing a
    name by hand risks a mismatch (e.g. importing an asset, rigging it,
    then fat-fingering the name on Save As creates a stray new asset
    folder instead of saving into the right one). Creating a brand-new
    asset's folder structure is now "Create Asset Folders"'s job
    (create_asset_folder_structure) — Save As just assumes the asset
    already exists and picks from what's there.
    """
    if cmds.window(SAVE_AS_WINDOW, exists=True):
        cmds.deleteUI(SAVE_AS_WINDOW)

    window = cmds.window(SAVE_AS_WINDOW, title="Save As", sizeable=False, width=380)
    cmds.columnLayout(adjustableColumn=True, columnAlign="left", rowSpacing=6, columnOffset=("both", 12))

    cmds.text(label="")  # top spacer
    cmds.text(label="Save As new file type", font="boldLabelFont", align="left")
    cmds.separator(height=10, style="in")

    project_path_at_open = get_current_project(warn_if_missing=False)
    existing_shots = list_existing_shots(project_path_at_open) if project_path_at_open else []
    existing_asset_types = list_asset_category_types(project_path_at_open) if project_path_at_open else []

    save_as_type_radio = cmds.radioButtonGrp(
        label="Save As",
        labelArray2=("Asset", "Shot"),
        numberOfRadioButtons=2,
        select=1,
        enable2=bool(existing_shots),
        columnWidth3=(70, 90, 90),
    )

    cmds.separator(height=10, style="in")
    cmds.text(label="Asset", font="boldLabelFont", align="left")

    # Type (2.27.0) — char/environ/prop plus any custom asset types Todd
    # has created. Picked before Task so the Asset Name list below can be
    # filtered to just that type's assets — added because custom types
    # previously had no way to be selected here at all (Asset Name was a
    # flat list across every type with no indication of which type each
    # asset belonged to).
    cmds.rowLayout(numberOfColumns=2, columnWidth2=(90, 220), adjustableColumn=2)
    cmds.text(label="Type")
    asset_type_dropdown = cmds.optionMenu(enable=bool(existing_asset_types))
    if existing_asset_types:
        for type_name in existing_asset_types:
            cmds.menuItem(label=type_name, parent=asset_type_dropdown)
    else:
        cmds.menuItem(label="No asset types yet", parent=asset_type_dropdown)
    cmds.setParent("..")

    asset_task_radio = cmds.radioButtonGrp(
        label="Task",
        labelArray4=("Model", "Rig", "LookDev", "FX"),
        numberOfRadioButtons=4,
        select=1,
        columnWidth5=(70, 80, 70, 80, 60),
    )

    cmds.rowLayout(numberOfColumns=2, columnWidth2=(90, 220), adjustableColumn=2)
    cmds.text(label="Asset Name")
    asset_name_dropdown = cmds.optionMenu(enable=False)
    cmds.menuItem(label="No assets of this type", parent=asset_name_dropdown)
    cmds.setParent("..")

    cmds.separator(height=10, style="in")
    cmds.text(label="Shot", font="boldLabelFont", align="left")

    cmds.rowLayout(numberOfColumns=2, columnWidth2=(140, 140), adjustableColumn2=2)
    shot_dropdown = cmds.optionMenu(enable=False)
    for shot_name in existing_shots:
        cmds.menuItem(label=shot_name, parent=shot_dropdown)
    task_dropdown = cmds.optionMenu(enable=False)
    for task_label in ("Previs", "Anim", "Lighting", "FX"):
        cmds.menuItem(label=task_label, parent=task_dropdown)
    cmds.setParent("..")

    cmds.rowLayout(numberOfColumns=2, columnWidth2=(90, 220), adjustableColumn=2)
    cmds.text(label="Version")
    version_dropdown = cmds.optionMenu(enable=False)
    cmds.setParent("..")

    cmds.separator(height=10, style="in")

    def compute_asset_preview():
        project_path = get_current_project(warn_if_missing=False)
        if not project_path:
            return "Creating: ____"

        if not existing_asset_types:
            return "No asset types yet — use Create Asset Folders"

        asset_type = cmds.optionMenu(asset_type_dropdown, query=True, value=True)
        task_map = {1: "model", 2: "rig", 3: "lookdev", 4: "fx"}
        task_name = task_map[cmds.radioButtonGrp(asset_task_radio, query=True, select=True)]
        asset_name = cmds.optionMenu(asset_name_dropdown, query=True, value=True)
        if not asset_name or asset_name == "No assets of this type":
            return "Creating: ____"

        asset_dir = os.path.join(project_path, "assets", asset_type, asset_name)
        if not os.path.isdir(asset_dir):
            return f"Creating: {asset_name}_{task_name}.v001.ma (asset not found yet)"
        dest_dir = asset_task_scenes_dir(asset_dir, task_name)

        stub = f"{asset_name}_{task_name}"
        next_version = get_next_asset_version(dest_dir, stub)
        return f"Creating: {stub}.v{next_version:03d}.ma"

    def refresh_asset_names(*_args):
        for item in cmds.optionMenu(asset_name_dropdown, query=True, itemListLong=True) or []:
            cmds.deleteUI(item)

        if not existing_asset_types:
            cmds.menuItem(label="No assets of this type", parent=asset_name_dropdown)
            cmds.optionMenu(asset_name_dropdown, edit=True, enable=False)
            update_preview()
            return

        asset_type = cmds.optionMenu(asset_type_dropdown, query=True, value=True)
        names = sorted({name for name, _path in list_all_assets(project_path_at_open, type_name=asset_type)})
        if names:
            for name in names:
                cmds.menuItem(label=name, parent=asset_name_dropdown)
            cmds.optionMenu(asset_name_dropdown, edit=True, enable=True)
            guessed = guess_asset_name_from_current_scene()
            if guessed in names:
                cmds.optionMenu(asset_name_dropdown, edit=True, value=guessed)
        else:
            cmds.menuItem(label="No assets of this type", parent=asset_name_dropdown)
            cmds.optionMenu(asset_name_dropdown, edit=True, enable=False)

        update_preview()

    def compute_shot_preview():
        if not existing_shots:
            return "Creating: ____"

        shot_name = cmds.optionMenu(shot_dropdown, query=True, value=True)
        task_name = cmds.optionMenu(task_dropdown, query=True, value=True).lower()
        version_choice = cmds.optionMenu(version_dropdown, query=True, value=True)

        if version_choice == "Create New Version":
            shots_dir = os.path.join(project_path_at_open, "shots")
            shot_path = os.path.join(shots_dir, shot_name)
            subpath = SHOT_TASK_MAYA_SUBPATH.get(task_name, ["work", "maya", "scenes"])
            dest_dir = os.path.join(shot_path, task_name, *subpath)
            stub = f"{shot_name}_{task_name}"
            next_version = get_next_asset_version(dest_dir, stub)
            return f"Creating: {stub}.v{next_version:03d}.ma"
        else:
            return f"Overwriting: {version_choice}"

    def update_preview(*_args):
        is_asset = cmds.radioButtonGrp(save_as_type_radio, query=True, select=True) == 1
        preview = compute_asset_preview() if is_asset else compute_shot_preview()
        cmds.text(preview_text, edit=True, label=preview)

    def refresh_version_dropdown(*_args):
        for item in cmds.optionMenu(version_dropdown, query=True, itemListLong=True) or []:
            cmds.deleteUI(item)

        if not existing_shots:
            cmds.menuItem(label="Create New Version", parent=version_dropdown)
            update_preview()
            return

        shot_name = cmds.optionMenu(shot_dropdown, query=True, value=True)
        task_name = cmds.optionMenu(task_dropdown, query=True, value=True).lower()

        shots_dir = os.path.join(project_path_at_open, "shots")
        shot_path = os.path.join(shots_dir, shot_name)
        subpath = SHOT_TASK_MAYA_SUBPATH.get(task_name, ["work", "maya", "scenes"])
        dest_dir = os.path.join(shot_path, task_name, *subpath)
        stub = f"{shot_name}_{task_name}"

        latest_file, _ = get_latest_versioned_file(dest_dir, stub)
        if latest_file:
            cmds.menuItem(label=latest_file, parent=version_dropdown)
        cmds.menuItem(label="Create New Version", parent=version_dropdown)

        update_preview()

    def on_save_as_type_change(*_args):
        is_asset = cmds.radioButtonGrp(save_as_type_radio, query=True, select=True) == 1

        cmds.optionMenu(asset_type_dropdown, edit=True, enable=(is_asset and bool(existing_asset_types)))
        cmds.radioButtonGrp(asset_task_radio, edit=True, enable=is_asset)
        cmds.optionMenu(asset_name_dropdown, edit=True, enable=(is_asset and bool(existing_asset_types)))
        update_preview()

        is_shot = (not is_asset) and bool(existing_shots)
        cmds.optionMenu(shot_dropdown, edit=True, enable=is_shot)
        cmds.optionMenu(task_dropdown, edit=True, enable=is_shot)
        cmds.optionMenu(version_dropdown, edit=True, enable=is_shot)
        if is_shot:
            refresh_version_dropdown()
        else:
            update_preview()

    cmds.radioButtonGrp(save_as_type_radio, edit=True, changeCommand=on_save_as_type_change)
    cmds.optionMenu(asset_type_dropdown, edit=True, changeCommand=refresh_asset_names)
    cmds.radioButtonGrp(asset_task_radio, edit=True, changeCommand=update_preview)
    cmds.optionMenu(asset_name_dropdown, edit=True, changeCommand=update_preview)
    cmds.optionMenu(shot_dropdown, edit=True, changeCommand=refresh_version_dropdown)
    cmds.optionMenu(task_dropdown, edit=True, changeCommand=refresh_version_dropdown)
    cmds.optionMenu(version_dropdown, edit=True, changeCommand=update_preview)

    def on_create(*_args):
        project_path = get_current_project()
        if not project_path:
            return

        is_asset = cmds.radioButtonGrp(save_as_type_radio, query=True, select=True) == 1

        if is_asset:
            if not existing_asset_types:
                cmds.warning("No asset types exist yet. Use Create Asset Folders first.")
                return

            asset_type = cmds.optionMenu(asset_type_dropdown, query=True, value=True)

            asset_task_map = {1: "model", 2: "rig", 3: "lookdev", 4: "fx"}
            task_name = asset_task_map[cmds.radioButtonGrp(asset_task_radio, query=True, select=True)]

            asset_name = cmds.optionMenu(asset_name_dropdown, query=True, value=True)
            if not asset_name or asset_name == "No assets of this type":
                cmds.warning("Select an asset name.")
                return

            asset_dir = os.path.join(project_path, "assets", asset_type, asset_name)
            if not os.path.isdir(asset_dir):
                cmds.warning(
                    f'No existing asset folder found named "{asset_name}" under type "{asset_type}". '
                    'Use Create Asset Folders to set it up first.'
                )
                return
            build_asset_task_structure(asset_dir)
            dest_dir = asset_task_scenes_dir(asset_dir, task_name)
            cmds.deleteUI(window)
            _save_scene_as(dest_dir, f"{asset_name}_{task_name}")
        else:
            if not existing_shots:
                cmds.warning("No shots exist yet.")
                return

            shot_name = cmds.optionMenu(shot_dropdown, query=True, value=True)
            task_name = cmds.optionMenu(task_dropdown, query=True, value=True).lower()
            version_choice = cmds.optionMenu(version_dropdown, query=True, value=True)

            shots_dir = os.path.join(project_path, "shots")
            shot_path = os.path.join(shots_dir, shot_name)
            subpath = SHOT_TASK_MAYA_SUBPATH.get(task_name, ["work", "maya", "scenes"])
            dest_dir = os.path.join(shot_path, task_name, *subpath)
            os.makedirs(dest_dir, exist_ok=True)
            stub = f"{shot_name}_{task_name}"

            cmds.deleteUI(window)

            if version_choice == "Create New Version":
                _save_scene_as(dest_dir, stub)
            else:
                file_path = os.path.join(dest_dir, version_choice)
                cmds.file(rename=file_path)
                align_maya_project()
                cmds.file(save=True, type="mayaAscii")
                cmds.file(modified=False)
                print(f"Saved scene: {file_path}")
                cmds.confirmDialog(title="Scene Saved", message=f"Saved to:\n{file_path}", button=["OK"])

    preview_text = cmds.text(label="", align="left")

    refresh_asset_names()

    if existing_shots:
        refresh_version_dropdown()
    else:
        update_preview()

    cmds.separator(height=10, style="in")

    cmds.columnLayout(adjustableColumn=True, columnAlign="center")
    cmds.rowLayout(numberOfColumns=2, columnAttach2=("both", "both"), columnOffset2=(0, 8))
    cmds.button(label="Create", width=85, command=on_create)
    cmds.button(label="Close", width=85, command=lambda *a: cmds.deleteUI(window))
    cmds.setParent("..")
    cmds.setParent("..")

    cmds.text(label="")  # bottom spacer

    cmds.showWindow(window)


# ============================================================
# SETUP FILE
# ============================================================

IMPORT_FILE_WINDOW = "importFileWindow"


def detect_existing_convention(dest_dir):
    """
    Look for <stub>.vNNN.<ext> files already in dest_dir. Returns
    (stub, highest_version, ext) for whichever stub has the most files/
    highest version, or None if nothing matches that pattern yet.
    """
    pattern = re.compile(r"^(.+)\.v(\d+)\.(\w+)$", re.IGNORECASE)
    best = None  # (stub, version, ext)

    if os.path.isdir(dest_dir):
        for name in os.listdir(dest_dir):
            match = pattern.match(name)
            if not match:
                continue
            stub, version, ext = match.group(1), int(match.group(2)), match.group(3)
            if best is None:
                best = [stub, version, ext]
            elif stub == best[0]:
                best[1] = max(best[1], version)

    return tuple(best) if best else None


def show_import_file_window():
    """
    "Ingest" (renamed 2.24.21 from "Import File" — Todd: confusing name,
    couldn't recall what it did from the label alone). Brings a
    third-party file into the pipeline's version-tracking scheme: pick
    the source file, pick a destination folder, then confirm/edit a base
    name and version number before it gets copied in renamed as
    <name>.vNNN.<ext> — matching whatever convention this tool uses, so
    future saves in that folder continue numbering from this point.
    """
    src_result = cmds.fileDialog2(fileMode=1, caption="Select File to Import")
    if not src_result:
        return
    src_path = src_result[0]
    src_filename = os.path.basename(src_path)
    src_stub, src_ext_dot = os.path.splitext(src_filename)
    src_ext = src_ext_dot.lstrip(".") or "ma"

    dest_result = cmds.fileDialog2(fileMode=3, caption="Select Destination Folder")
    if not dest_result:
        return
    dest_dir = dest_result[0]

    existing = detect_existing_convention(dest_dir)
    if existing:
        default_stub, highest_version, default_ext = existing
        default_version = highest_version + 1
    else:
        default_stub = src_stub
        default_version = 1
        default_ext = src_ext

    if cmds.window(IMPORT_FILE_WINDOW, exists=True):
        cmds.deleteUI(IMPORT_FILE_WINDOW)

    window = cmds.window(IMPORT_FILE_WINDOW, title="Ingest", sizeable=False, width=380)
    cmds.columnLayout(adjustableColumn=True, columnAlign="left", rowSpacing=6, columnOffset=("both", 12))

    cmds.text(label="")  # top spacer
    cmds.text(label="Ingest", font="boldLabelFont", align="left")
    cmds.separator(height=10, style="in")

    cmds.text(label=f"Source: {src_filename}", align="left")
    cmds.text(label=f"Destination: {dest_dir}", align="left")

    cmds.separator(height=10, style="in")

    cmds.rowLayout(numberOfColumns=2, columnWidth2=(90, 220), adjustableColumn=2)
    cmds.text(label="Base Name")
    base_name_field = cmds.textField(text=default_stub)
    cmds.setParent("..")

    cmds.rowLayout(numberOfColumns=2, columnWidth2=(90, 220), adjustableColumn=2)
    cmds.text(label="Version")
    version_field = cmds.textField(text=str(default_version).zfill(3))
    cmds.setParent("..")

    cmds.separator(height=10, style="in")

    preview_text = cmds.text(label="", align="left")

    def update_preview(*_args):
        base_name = cmds.textField(base_name_field, query=True, text=True).strip() or "file"
        version_text = cmds.textField(version_field, query=True, text=True).strip()
        try:
            version_str = str(int(version_text)).zfill(3)
        except ValueError:
            version_str = "___"
        cmds.text(preview_text, edit=True, label=f"Will be saved as: {base_name}.v{version_str}.{default_ext}")

    cmds.textField(base_name_field, edit=True, textChangedCommand=update_preview)
    cmds.textField(version_field, edit=True, textChangedCommand=update_preview)
    update_preview()

    cmds.separator(height=10, style="in")

    def on_import(*_args):
        base_name = cmds.textField(base_name_field, query=True, text=True).strip()
        if not base_name:
            cmds.warning("Enter a base name.")
            return

        version_text = cmds.textField(version_field, query=True, text=True).strip()
        try:
            version_num = int(version_text)
        except ValueError:
            cmds.warning(f'"{version_text}" is not a valid version number.')
            return

        final_name = f"{base_name}.v{str(version_num).zfill(3)}.{default_ext}"
        final_path = os.path.join(dest_dir, final_name)

        if os.path.isfile(final_path):
            cmds.warning(f"File already exists: {final_path}")
            return

        try:
            shutil.copy2(src_path, final_path)
        except Exception as e:
            cmds.warning(f"Could not import file: {e}")
            return

        cmds.deleteUI(window)
        print(f"Imported file: {final_path}")
        cmds.confirmDialog(
            title="File Imported",
            message=(
                f"Imported as:\n{final_path}\n\n"
                f"Future saves in this folder will continue from v{str(version_num).zfill(3)}."
            ),
            button=["OK"],
        )

    cmds.columnLayout(adjustableColumn=True, columnAlign="center")
    cmds.rowLayout(numberOfColumns=2, columnAttach2=("both", "both"), columnOffset2=(0, 8))
    cmds.button(label="Import", width=85, command=on_import)
    cmds.button(label="Cancel", width=85, command=lambda *a: cmds.deleteUI(window))
    cmds.setParent("..")
    cmds.setParent("..")

    cmds.text(label="")  # bottom spacer

    cmds.showWindow(window)


def gather_setup_data(project_path, prefix):
    """Collect everything needed to recreate this project's structure and settings."""
    data = {
        "project_name": os.path.basename(project_path.rstrip(os.sep)),
        "shot_prefix": prefix,
        "output_width": cmds.optionVar(query=OUTPUT_WIDTH_OPTVAR) if cmds.optionVar(exists=OUTPUT_WIDTH_OPTVAR) else None,
        "output_height": cmds.optionVar(query=OUTPUT_HEIGHT_OPTVAR) if cmds.optionVar(exists=OUTPUT_HEIGHT_OPTVAR) else None,
        "start_frame": cmds.optionVar(query=START_FRAME_OPTVAR) if cmds.optionVar(exists=START_FRAME_OPTVAR) else None,
        "end_frame": cmds.optionVar(query=END_FRAME_OPTVAR) if cmds.optionVar(exists=END_FRAME_OPTVAR) else None,
    }

    assets_dir = os.path.join(project_path, "assets")
    asset_types = {}
    standalone_present = []

    if os.path.isdir(assets_dir):
        for type_name in sorted(os.listdir(assets_dir)):
            type_path = os.path.join(assets_dir, type_name)
            if not os.path.isdir(type_path):
                continue
            if type_name in ASSET_STANDALONE_TYPES:
                standalone_present.append(type_name)
                continue
            names = sorted(
                n for n in os.listdir(type_path)
                if os.path.isdir(os.path.join(type_path, n))
            )
            asset_types[type_name] = names

    data["asset_types"] = asset_types
    data["standalone_asset_types"] = standalone_present

    shot_numbers = []
    if prefix:
        scenes_dir = os.path.join(project_path, "shots")
        shot_numbers = get_existing_shot_numbers(scenes_dir, prefix)
    data["shot_numbers"] = shot_numbers

    return data


def save_setup():
    """Save the current project's settings and folder structure (assets/shots) to a JSON file."""
    project_path = get_current_project()
    if not project_path:
        return

    prefix = get_shot_prefix(warn_if_missing=False)
    data = gather_setup_data(project_path, prefix)

    file_result = cmds.fileDialog2(fileMode=0, caption="Save Setup As", fileFilter="TP_pipe Setup (*.json)")
    if not file_result:
        return

    file_path = file_result[0]
    if not file_path.lower().endswith(".json"):
        file_path += ".json"

    try:
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        cmds.warning(f"Failed to save setup: {e}")
        return

    print(f"Setup saved: {file_path}")
    cmds.confirmDialog(title="Setup Saved", message=f"Setup saved to:\n{file_path}", button=["OK"])


def _load_setup_file():
    """Prompt for a setup JSON file and return its parsed contents, or None if cancelled/invalid."""
    result = cmds.fileDialog2(fileMode=1, caption="Select Setup File", fileFilter="TP_pipe Setup (*.json)")
    if not result:
        return None

    try:
        with open(result[0], "r") as f:
            return json.load(f)
    except Exception as e:
        cmds.warning(f"Failed to read setup file: {e}")
        return None


def _prepare_load_destination(data):
    """Ask for a parent folder, create/reuse <parent>/<saved project name>, and set it as current project."""
    parent_result = cmds.fileDialog2(fileMode=3, caption="Select Location to Load Setup Into")
    if not parent_result:
        return None

    project_name = data.get("project_name") or "Project"
    project_path = os.path.join(parent_result[0], project_name)
    os.makedirs(project_path, exist_ok=True)
    cmds.optionVar(stringValue=(CURRENT_PROJECT_OPTVAR, project_path))
    cmds.savePrefs(general=True)
    build_menu()

    return project_path


def _apply_loaded_settings(data):
    """Restore shot prefix / output size / frame range optionVars, and apply them to the open scene."""
    prefix = data.get("shot_prefix")
    if prefix:
        cmds.optionVar(stringValue=(SHOT_PREFIX_OPTVAR, prefix))

    if data.get("output_width") is not None and data.get("output_height") is not None:
        cmds.optionVar(intValue=(OUTPUT_WIDTH_OPTVAR, data["output_width"]))
        cmds.optionVar(intValue=(OUTPUT_HEIGHT_OPTVAR, data["output_height"]))

    if data.get("start_frame") is not None:
        cmds.optionVar(intValue=(START_FRAME_OPTVAR, data["start_frame"]))
    if data.get("end_frame") is not None:
        cmds.optionVar(intValue=(END_FRAME_OPTVAR, data["end_frame"]))

    apply_saved_settings()


def _rebuild_assets(project_path, data):
    """Recreate asset type/name/task folders from saved data. Folders only — no scene files."""
    assets_dir = os.path.join(project_path, "assets")
    os.makedirs(assets_dir, exist_ok=True)

    for standalone_type in data.get("standalone_asset_types", []):
        os.makedirs(os.path.join(assets_dir, standalone_type), exist_ok=True)

    for type_name, asset_names in data.get("asset_types", {}).items():
        type_path = os.path.join(assets_dir, type_name)
        os.makedirs(type_path, exist_ok=True)
        for asset_name in asset_names:
            build_asset_task_structure(os.path.join(type_path, asset_name))


def _rebuild_shots(project_path, prefix, shot_numbers, tasks=None):
    """
    Recreate shots/<shot> folders for every saved shot number.
    tasks=None builds the full shot template; otherwise only the given
    subset of tasks (e.g. ["anim"] or ["lighting"]) is built.
    """
    if not shot_numbers or not prefix:
        return

    scenes_dir = get_scenes_directory(project_path)
    task_names = tasks if tasks is not None else list(SHOT_TASK_STRUCTURE.keys())

    for number in shot_numbers:
        shot_path = os.path.join(scenes_dir, format_shot_name(prefix, number))
        os.makedirs(shot_path, exist_ok=True)
        for task in task_names:
            task_path = os.path.join(shot_path, task)
            os.makedirs(task_path, exist_ok=True)
            build_folder_tree(task_path, SHOT_TASK_STRUCTURE.get(task, {}))


def load_setup_full():
    """Recreate everything from a saved setup file: settings, assets, and full shot structure. No scene files."""
    data = _load_setup_file()
    if not data:
        return

    project_path = _prepare_load_destination(data)
    if not project_path:
        return

    for rel_path in PROJECT_SKELETON_DIRS:
        os.makedirs(os.path.join(project_path, rel_path), exist_ok=True)

    username = getpass.getuser()
    sandbox_dir = os.path.join(project_path, "sandbox", username)
    for rel_path in SANDBOX_PUBLISH_DIRS:
        os.makedirs(os.path.join(sandbox_dir, rel_path), exist_ok=True)

    _rebuild_assets(project_path, data)
    _apply_loaded_settings(data)
    _rebuild_shots(project_path, data.get("shot_prefix"), data.get("shot_numbers", []), tasks=None)

    print(f"Setup fully loaded into: {project_path}")
    cmds.confirmDialog(title="Setup Loaded", message=f"Setup loaded into:\n{project_path}", button=["OK"])


def load_setup_anim_only():
    """Recreate settings and shot folders, but only the anim task inside each shot."""
    data = _load_setup_file()
    if not data:
        return

    project_path = _prepare_load_destination(data)
    if not project_path:
        return

    _apply_loaded_settings(data)
    _rebuild_shots(project_path, data.get("shot_prefix"), data.get("shot_numbers", []), tasks=["anim"])

    print(f"Anim-only setup loaded into: {project_path}")
    cmds.confirmDialog(
        title="Setup Loaded",
        message=f"Anim-only shot structure loaded into:\n{project_path}",
        button=["OK"],
    )


def load_setup_lighting_only():
    """Recreate settings and shot folders, but only the lighting task inside each shot."""
    data = _load_setup_file()
    if not data:
        return

    project_path = _prepare_load_destination(data)
    if not project_path:
        return

    _apply_loaded_settings(data)
    _rebuild_shots(project_path, data.get("shot_prefix"), data.get("shot_numbers", []), tasks=["lighting"])

    print(f"Lighting-only setup loaded into: {project_path}")
    cmds.confirmDialog(
        title="Setup Loaded",
        message=f"Lighting-only shot structure loaded into:\n{project_path}",
        button=["OK"],
    )


# ============================================================
# ENTRY POINT
# ============================================================

def onMayaDroppedPythonFile(*_args):
    """
    Maya calls this specifically when the script is dragged into the
    viewport, instead of just running the file's top-level code. Defining
    it here removes Maya's "does not contain drop function" warning.
    """
    build_menu()


# Also build the menu on a normal run (e.g. pasted into the Script Editor
# or run via Python > Run Script...), since onMayaDroppedPythonFile is only
# called by Maya's drag-and-drop mechanism specifically. build_menu()
# always tears down any existing menu first, so calling it from both paths
# is harmless.
build_menu()
