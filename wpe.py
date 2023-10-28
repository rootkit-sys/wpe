from utils import MPV, DesktopHWND, CheckFile, KeyHook, logo, MPVThread
from threading import Thread

def play(playlist, loop):

	print("\n\tInitializing MPV...", end = "")
	player = MPV(ytdl = True)
	player.wid = DesktopHWND()
	print("OK")
	if loop:
		player.loop_playlist = "inf"
	print("\tLoop playlist:", loop)
	for track in playlist:
		player.playlist_append(track)
	print("\n\tYTDL can require more time for load.")
	print("\tPress F10 for hide/unhide console window.\n")
	thread_mpv = Thread(target=MPVThread, args=(player, ), daemon=True)
	thread_mpv.start()
	thread_hook = Thread(target=KeyHook, args=(), daemon=True)
	thread_hook.start()

	while 1:
#isAlive()
		if thread_mpv.is_alive() and len(player.playlist) > 1:
			inp = "Type 'play/pause', 'next/prev', 'show', 'stop'"
		if thread_mpv.is_alive() and len(player.playlist) == 1:
			inp = "Type 'play/pause', 'show', 'stop'"
		if player.pause:
			inp = "Type 'play' for playing"

		cmd = input("(%s)>" % (inp))

		if cmd == "stop":
			while 1:
				try:
					player.terminate()
					player.playlist
				except OSError:
					break
			break

		elif cmd == "next":
			try:
				player.playlist_next(mode="weak")
			except Exception as error:
				print("\tLast track.")

		elif cmd == "prev":
			try:
				player.playlist_prev(mode="weak")
			except Exception as error:
				print("\tFirst track.")

		elif cmd == "pause":

			if player.pause:
				print("\tAlready.")
			else:
				player.command("cycle", "pause")
				print("\tPause.")

		elif cmd == "play":
			if player.pause:
				player.command("cycle", "pause")
				print("\tPlay.")
			else:
				print("\tAlready.")

		elif cmd == "show":
			print("\nPlaylist:")
			c = 1
			for _ in player.playlist:
				if "current" in _.keys():
					if player.pause:
						print("\t[%i] || %s" % (c, _["filename"]))
					else:
						print("\t[%i] ►  %s" % (c, _["filename"]))
				else:
					print("\t[%i]    %s" % (c, _["filename"]))
				c += 1

def cli():

	print(logo)
	playlist = []
	cmd = ""
	while cmd != "stop":

		if playlist == []:
			inp = "Add file on playlist use option 'add' or type 'help'"
		elif playlist != []:
			inp = "Type 'play', 'clear' or 'show' for showing playlist"

		cmd = input("(%s)>" % (inp))
		
		if cmd == "clear":
			playlist = []
			print("\tPlaylist cleared.")
		
		elif cmd == "show":
			if playlist != []:
				print("\nPlaylist:")
				c = 1
				for _ in playlist:
					print("\t[%i] %s" % (c, _))
					c += 1
			else:
				print("\tEmpty playlist")
		
		elif cmd[0:4] == "add ":
			cmd_split = cmd.split()
			if len(cmd_split) > 1:
				file = cmd_split[1]
				if file[0:4] == "http" or CheckFile(file):
					playlist.append(file)
					print("\t'%s' - added in playlist." % (file))
				else:
					print("\t'%s' - not found." % (file))
		
		elif cmd[0:4] == "play":
			if playlist != []:
				loop = False
				play_split = cmd.split()
				if len(play_split) > 1:

					if play_split[-1] == "loop":
						loop = True
				play(playlist, loop)
			else:
				print("\tEmpty playlist")

		elif cmd == "help":

			print("\n\tHelp page.\n")
			print("\tCommand 'add [file or url]' - add file or URL on playlist.")
			print("\tCommand 'clear' - clear playlist.")
			print("\tCommand 'show' - show playlist.")
			print("\tCommand 'stop' - quit.\n")

	print("\nByBy:*")

cli()