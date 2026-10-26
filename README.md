Installation & Documentation found here

https://docs.google.com/document/d/10WqRuIbrM-SlY68Tq0pRLI35-FTzgNZyc_-Meeit5QY/edit?usp=drive_link

v 3.27.2
- complete revamp of the project xfer tool to make redundant tasks easier

v 3.25.1
- updated "Create Custom Folder" tool to accommodate multi selection in all cases
- added User Pref Xfer which can be used to send user level preferences:
View Settings
Projects Lists
Machine Settings 
- includes ability to send prefs to connected google drive for remote access

v 3.24.1
- introduced a tool to connect to google drive as a drive letter.  Tool lives in TP_pipe>Tp_pipe.
This will not work on school machines..  
Once it is set up, project xfer tool now has a button to sync with google drive so anything selected will save locally and on a specified folder in google drive.

v 3.22.1

open/save as
- added support for subtasks
- added sorting option for subtasks and user in file display

asset manager
- added support for subtasks
- added toggle for listing by task or by name

v 3.20.0
open / save as
- added checkboxes and "hide checked" so user can turn off things that are unnecessary
- drag and drop reorder to assets (not applied to shots.. shots numerical makes sense.. no need to arrange)
- toggle for Task/Name - this changes how the assets are viewed... by task with names below.
or by names with tasks below
- thumbnail is now freeform
- added checkbox and hide checked to file list window
- also allow for viewing non pipelined files (only maya files) in the file view.. with separator for visual ease (this is only for open)

create asset folders
- added task checkboxes to select which tasks you want added upon creation
- included custom option - because why not

create shot folders
- added task checkboxes to select which tasks you want added upon creation
- included custom option - because why not

create tasks
- allows user to create task folders 
- can multiselect in the left window

create workspaces
- allows user to create workspace folders
- can multiselect in the left window
- added a variety of workspaces as options
- houdini and nuke also create default folders 

Load Textures
- one click to make textures visible in gui (useful for animation)

v3.18.1
- fixed broken texture connect tool (and moved to utlity section)
- added relink references if they dont attach due to folder structure name change due to different computers or whatever..
but also added the relinking to happen automatically for references, caches and textures. Button is just for manual use.
- controlled location for exports function to send to task/output/exports (based on open scene)

v 3.17.1
- added playblast function - which is basically mayas playblast function.. but autopupulates the output location to control file structure
- added "browse" function to file>open and file>save as which gives access to the full hard drive for saving and importing outside the pipeline

v 3.15.0
- a re-org of the tools and their groupings in the menu system (to be less confusing)
- all project/file sharing, transferring, syncing has been consolidated into one tool in TP_pipe (Project Xfer)

v 3.14.0 (pi!)
- consolidated everything down to one file - pipeline_menu.py
- added file xfer assist (in the TP_Pipe menu)
  with the UI of asset manager.. this tool allows you to go through all the files on your project and build a list of files to transfer to another machine.  select all files you want and add them to a list.  choose options for including publishes and dependencies..
  then build a folder 
  <project name>/io/file_xfer_assist/<todays date>
  includes a json file.  then run the tool, point to the dated folder (wherever you choose to save it) and click import
