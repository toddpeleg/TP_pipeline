Installation & Documentation found here

https://docs.google.com/document/d/10WqRuIbrM-SlY68Tq0pRLI35-FTzgNZyc_-Meeit5QY/edit?usp=drive_link

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

v 3.12.6
- fixes to asset manager implementation.. adding group names to the in scene list for clarity
- fixed asset manager cache bugs
  
v 3.12.4
- added Set Shot Range tool
  allows adjusting of shot frame range in current scene and saves
  adjust current scene frame range without saving
  update (modify) shot range for current scene

  
v 3.12.0
- Shot Range: Start/End in Save As (shots), saved inside the scene file and applied to the timeline + render settings; shown as a Range column in Save As / Open Scene
- Asset Manager: cache rows show their shot range; the first cache in a clean scene sets the frame range; new Update and Continue button
- Export Cache: cache version now matches the scene version (asks before overwriting); a second copy of a rig caches under its own name
- Create Shot Folders: Create / Create and Close / Cancel; Shot Count, Step and Prefix carry over when switching Scene Folders
- Fix: Rename Project was grayed out when only one project existed

v 3.11.0
- added the ability to have thumbnails in the open / save as and asset manager menus
- added github link to the TP_pipe menu
- tool auto checks for updates upon launch (pings github) and alerts if theres is an update
- clicking on the current version manually checks for an update

v 3.8.0
- updated create shot folders / new UI 
- followed new UI theme into create asset folders and create custom folders
- revamped asset manager to match new UI
- adjusted open and save as menu to include the switch style toggle between assets and shots
- rig publish now includes _rigRoot_set from rig file

v 3.3.2
- ability to create scene files as separate folders with shots nested below instead of sc01_sh0000

v 3.2.9
- Multi-user file visibility (removed the current-user filter from Open Scene and Save As, so all correctly-named files from any user show up)
- Refresh button on Open Scene's browse column, with expand-state and selection preserved across refresh

v 3.2.7 
— File > Export (Export All / Export Selection, pure mirror of Maya's native menu)
