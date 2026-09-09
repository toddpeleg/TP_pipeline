import maya.cmds as cmds
import os

def workspaceExists(p):
    p = os.sep.join((p, 'workspace.mel'))
    return os.path.isfile(p)

def setProjectFromScene():
    fp = cmds.file(q=True, sn=True)
    if fp:
        fp = os.path.normpath(fp)
        p, f = os.path.split(fp)
        psplit = p.split(os.sep)
        if psplit[-1] == 'scenes':
            newWsDir = os.sep.join(psplit[0:-1])
            if workspaceExists(newWsDir):
                cmds.workspace(newWsDir, openWorkspace=True)
                currentWsDir = cmds.workspace(q=True, fn=True)
                print('Project set to: %s' % currentWsDir)

job = cmds.scriptJob(permanent=True, event=["SceneOpened", setProjectFromScene])


# ------------------------------------------------------------------
# TP_pipe Pipeline Menu — Project Settings auto-apply (early)
# ------------------------------------------------------------------
# These optionVar keys must match the ones used in pipeline_menu.py's
# "Project Settings" section (Output Size / Starting Frame Number).
# Reading them here means saved settings get applied on every scene open,
# even in a fresh Maya session where pipeline_menu.py hasn't been run yet.

OUTPUT_WIDTH_OPTVAR = "outputWidth"
OUTPUT_HEIGHT_OPTVAR = "outputHeight"
START_FRAME_OPTVAR = "startFrame"
END_FRAME_OPTVAR = "endFrame"  # scene timeline end, paired with START_FRAME_OPTVAR (2.32.0)


def early_apply_saved_settings():
    applied = []

    if cmds.optionVar(exists=OUTPUT_WIDTH_OPTVAR) and cmds.optionVar(exists=OUTPUT_HEIGHT_OPTVAR):
        width = cmds.optionVar(query=OUTPUT_WIDTH_OPTVAR)
        height = cmds.optionVar(query=OUTPUT_HEIGHT_OPTVAR)
        cmds.setAttr("defaultResolution.width", width)
        cmds.setAttr("defaultResolution.height", height)
        applied.append(f"Output Size: {width} x {height}")

    if cmds.optionVar(exists=START_FRAME_OPTVAR):
        start_frame = cmds.optionVar(query=START_FRAME_OPTVAR)
        cmds.playbackOptions(minTime=start_frame, animationStartTime=start_frame)
        applied.append(f"Starting Frame: {start_frame}")

    if cmds.optionVar(exists=END_FRAME_OPTVAR):
        end_frame = cmds.optionVar(query=END_FRAME_OPTVAR)
        cmds.playbackOptions(maxTime=end_frame, animationEndTime=end_frame)
        applied.append(f"Ending Frame: {end_frame}")

    if applied:
        print("TP_pipe: applied saved project settings on scene open:")
        for line in applied:
            print(f"  {line}")


early_settings_job = cmds.scriptJob(permanent=True, event=["SceneOpened", early_apply_saved_settings])


# ------------------------------------------------------------------
# TP_pipe menu — auto-load on Maya startup
# ------------------------------------------------------------------
# pipeline_menu.py is installed into this same scripts folder by its own
# "Install Setup Files" menu item. Instead of a plain "import pipeline_menu"
# (which would cache it in sys.modules under the name "pipeline_menu"), we
# load it under a different internal name here. That way, if you later
# drag a newer pipeline_menu.py into the viewport to test changes, Maya
# won't mistake it for this already-cached module and reuse stale code —
# the dropped file always gets freshly executed.
#
# The load itself is deferred with evalDeferred, since userSetup.py runs
# very early in Maya's startup sequence — before the main menu bar
# ($gMainWindow) is guaranteed to exist yet. Building the menu directly
# here can silently fail; evalDeferred waits until Maya's UI is fully
# ready before running it.
#
# Wrapped in a try/except so a missing file (not yet installed) or running
# in batch mode (no UI, e.g. Render/mayapy) doesn't break Maya startup.

def _load_tp_pipe_debug_menu():
    try:
        import importlib.util

        pipeline_menu_path = os.path.join(cmds.internalVar(userScriptDir=True), "pipeline_menu.py")
        spec = importlib.util.spec_from_file_location("tp_pipe_installed_menu", pipeline_menu_path)
        tp_pipe_installed_menu = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tp_pipe_installed_menu)
    except Exception as e:
        print(f"TP_pipe menu: could not load pipeline_menu.py ({e})")


cmds.evalDeferred(_load_tp_pipe_debug_menu)
