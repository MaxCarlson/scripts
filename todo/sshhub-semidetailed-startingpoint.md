# ssh-manager latest(?) spexifications


## Main prpject

also, it would be very cool if it was integrated with ssh manager(unsure on ssh maanager prpgress but it cann be found @~/scripts/modules/sshmanager/) and the idea behind it is to make it perfect simple to ssh into any machine i have creds for, copy creds, ideally do as much as possible to make it easy to add new machines, setup/install ssh server, ensure it runs automarocally at boot, on new machines (and have it run on startup).

another nice fewture migjt be the  functionality of if on a machine which has acccess to another machine (via ssh keys), setup a function that can be run that turns on password logons on the specic machine, then waits for the user to attempt to ssh onto the machine from the new machine (attempts/and time-limited), then aufomatically handles setting up an ssh key on the new device (remember, whatever devices sshhub connects to are hubs, and have scripts (which contains ssh-hub obviously and will have performed whateber fequires setup ssh-hub does), and dotfiles), contuining to ensure that the new machines ssh key is added to the ssh-hub ecrypted secrets howver thats handled with with git, along with ensuring its now part of the ssh-hub network (for now thay should require downloading scripts and dotfiles repo, but a minimalist version if future could be interesting)

needs to work for both linux and w11 pwsh, and Termux. At (usually ~/scripts, except on windows where its ~/src/scripta...somehwta annoying) ~/scripts/modules/cross_platform/ is my cros platofrm python module, where you'll find any cross platform functionaloty you should need (and if ots nkt there add it to the list of missing cross-platform functionality, and the app/module which needs what funcrionalsity - if youre not the first to need the functionality, just wrtie down youre appp/script/module name, starting a list).

### Please setup as solo function so its working asap, then only once ssh-hub is nearing completion bather xhnaging it

I want a python script that updates my 2 main repos, dotfiles, scrips from anywhere on my machine, i spend lots of time typing "cds; gl; gp; cdd; gl; gp" (withosemi colonons onvioisly, but you should get the idea - the sceipts amd dotfiles repo are repos that live on my every machine)
