"""
pyAKBetterIncrementAndSave.py
Alex Kline | dev[at]alexkline<dot>com
2020-02-19
http://blog.alexkline.com/2020/02/19/maya-better-increment-and-save/
This Maya plugin overrides the default Increment and Save menu command to accept only scenes with a valid v[0-9]+ version pattern.
In addition, it will also update the Version Label field in the render settings with a matching version.
See examples below, and blog post above for more information.
scenename_v001.ma -> scenename_v002.ma
scenename_v001_desc.ma -> scenename_v002_desc.ma
"""

import sys
import maya.api.OpenMaya as om
import maya.cmds as cmds
import maya.mel as mel
import glob
import re
import os

cusCall_updateVersionToken = None

def maya_useNewAPI():
    """The presence of this function tells Maya that the plugin produces, and expects to be passed, objects created using the Maya Python API 2.0."""
    pass

class BetterIncrementAndSave(om.MPxCommand):
    kPluginCmdName = "bias"

    def __init__(self):
        om.MPxCommand.__init__(self)
        
    @staticmethod
    def cmdCreator():
        return BetterIncrementAndSave()
        
    def _message(self, message):
        print("pyAKBetterIncrementAndSave.py | {}".format(message))
        
    def _check_scene(self):
        """Validate scene, find version based on convention, and return relevant information."""
        
        scenePath = cmds.file(sn=True, q=True)
        if scenePath == "":
            cmds.confirmDialog(title="Scene Not Saved!", message="Please save your current scene with a valid version pattern in the filename, v[0-9]+.\nIn example, scenename_v001.ma OR scenename_v001_desc.ma")
            self._message("Current scene is not saved!  Please save your scene and include a valid version pattern in the filename, v[0-9]+.  In Example, scenename_v001.ma OR scenename_v0001_desc.ma")
            return False
        
        sceneDir, sceneName = os.path.split(scenePath)
        fileName, fileExt = os.path.splitext(sceneName)

        # checking if version pattern exists in file
        ver = ""
        try:
            ver = re.search("v[0-9]+", fileName).group(0)
        except:
            self._message("current scene filename does contain a valid version pattern, v[0-9]+.  please save your scene with a valid version tag: v###")
            return False

        return {"scenePath": scenePath, "sceneDir": sceneDir, "sceneName": sceneName, "fileName": fileName, "fileExt":fileExt, "version": ver }

    def doIt(self, args):
        
        checks = self._check_scene()
        if not checks:
            return
            
        def _increment_version(curVersion):

            vNum = curVersion[1:]
            vLen = len(vNum)
            vNumUp = str(int(vNum) + 1)
            newVersion = "v{}".format(vNumUp.zfill(vLen))
            return newVersion

        def _get_file_type():

            if checks["fileExt"] == ".ma":
                return "mayaAscii"
            elif checks["fileExt"] == ".mb":
                return "mayaBinary"

        def _make_latest(inPath):
            
            latestFile = glob.glob("{}/*{}".format(os.path.split(inPath)[0], checks["fileExt"]))[-1]

            ver = re.search("v[0-9]+", inPath).group(0)
            lVer = _increment_version(re.search("v[0-9]+", latestFile).group(0))

            nPath = re.sub(ver, lVer, inPath)

            return nPath, lVer
            
        # replace current version with new one
        version = _increment_version(checks["version"])
        nScenePath = re.sub(checks["version"], version, checks["scenePath"])
        
        # check if version of scene already exists
        if os.path.isfile(nScenePath):

            mLatePath , mLateVer = _make_latest(nScenePath)
            prompt = cmds.confirmDialog(title="File Conflict",
                                        message="%s already exists already.  What would you like to do?" % (os.path.split(nScenePath)[-1]),
                                        button=["overwrite", "make latest ({})".format(mLateVer), "cancel"]
                                        )

            if prompt == "overwrite":
                pass
            elif prompt == "make latest ({})".format(mLateVer):
                nScenePath = mLatePath
            else:
                self._message("user cancelled incrementAndSave process.")
                return

        # save new file
        cmds.file(rename=nScenePath)
        cmds.file(save=True, f=True, type=_get_file_type())
        self._message("incremented and saved - {}".format(nScenePath))
        
def update_version_label(*args):
    """Update render settings version label."""
    
    bias = BetterIncrementAndSave()
    checks = bias._check_scene()
    if not checks:
        return
    cmds.setAttr("defaultRenderGlobals.renderVersion", checks["version"], type="string")


def initializePlugin( mobject ):
    """Initialize the plug-in when Maya loads it."""
    
    global cusCall_updateVersionToken
    mplugin = om.MFnPlugin(mobject, vendor="Alex Kline", version="1.0", apiVersion="2.0" )
    
    try:
        mplugin.registerCommand(BetterIncrementAndSave.kPluginCmdName, BetterIncrementAndSave.cmdCreator )
        mel.eval("source incrementAndSaveScene.mel")
        mel.eval("""global proc incrementAndSaveScene( int $force )
                    {
                        bias;
                    }""")
        cusCall_updateVersionToken = om.MSceneMessage.addCallback(om.MSceneMessage.kAfterSave, update_version_label)
    except:
        sys.stderr.write( "Failed to register command: " + BetterIncrementAndSave.kPluginCmdName )

def uninitializePlugin( mobject ):
    """Uninitialize the plug-in when Maya un-loads it."""
    
    global cusCall_updateVersionToken
    mplugin = om.MFnPlugin( mobject )
    
    try:
        mplugin.deregisterCommand( BetterIncrementAndSave.kPluginCmdName )
        om.MSceneMessage.removeCallback(cusCall_updateVersionToken)
        mel.eval("source incrementAndSaveScene.mel")
    except:
        sys.stderr.write( "Failed to unregister command: " + BetterIncrementAndSave.kPluginCmdName )