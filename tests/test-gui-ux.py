#!/usr/bin/env python3
from pathlib import Path

GUI = Path(__file__).resolve().parents[1] / 'bin' / 'frozr-gui'
source = GUI.read_text()


def method(name, next_name):
    start = source.index(f'    {name}(')
    end = source.index(f'    {next_name}(', start)
    return source[start:end]


build_ui = method('buildUi', 'makeSection')
display = method('buildDisplaySection', 'buildStorageSection')
choose_after = method('chooseFile', 'inspectSelectedFile')
inspect_after = method('inspectSelectedFile', 'chooseStartupFile')
choose_startup = method('chooseStartupFile', 'inspectStartupSelectedFile')
inspect_startup = method('inspectStartupSelectedFile', 'updateStartupStatus')
set_startup = method('setSelectedAsStartupDisplay', 'resetStartupDisplay')
startup_preview = method('refreshStartupPreview', 'rotatePreview')
after_preview = method('refreshPreview', 'cleanupPreviewFile')

# One display hierarchy: the old separate Content/Startup top-level sections must stay gone.
assert 'buildDisplaySection()' in build_ui
assert 'buildContentSection()' not in source
assert 'buildStartupSection()' not in source
assert "makeSection('Display')" not in display
assert "makeSection('Content')" not in source
assert "makeSection('Power & Startup')" not in source

# The display hierarchy stays flat: phases are separated by whitespace/separators, not nested cards/frames.
assert "const outer = new Gtk.Box" in display
assert "makeSection('Display')" not in display
assert 'new Gtk.Frame()' not in display
assert "add_css_class('card')" not in display
assert "label: 'Before Linux starts'" in display
assert "label: 'After login'" in display
assert 'startupHeader.append(this.startupStatus)' in display
assert 'sessionHeader.append(this.afterLoginStatus)' in display
assert 'startupBody.append(startupHint)' in display
assert 'sessionBody.append(sessionHint)' in display
assert display.index("label: 'Before Linux starts'") < display.index("label: 'After login'")
assert 'sessionBody.append(editor)' in display
assert "label: 'Brightness'" in display
assert 'Shared by both phases' not in display
assert display.index("label: 'Brightness'") < display.index("label: 'Before Linux starts'")
assert 'brightnessApply.set_valign(Gtk.Align.CENTER)' in display
assert 'brightnessApply.set_hexpand(false)' in display
assert 'startupOrientationHeader' in display
assert 'startupMirrorHorizontalButton' in display
assert 'orientationHeader' in display
assert 'mirrorHorizontalButton' in display
assert 'startupPreviewStack' in display
assert 'previewStack' in display
assert display.count("set_size_request(360, 360)") == 2
assert display.count('set_draw_func(drawRoundMask)') == 2
assert 'refreshStartupPreview()' in source

# Animated previews are timer-driven texture sequences; hover/media widget state cannot pause them.
assert 'new Gtk.Video' not in source
assert 'Gtk.MediaFile' not in source
assert "add_named(this.startupPreviewPicture, 'picture')" in display
assert "add_named(this.previewPicture, 'picture')" in display
assert "this.startFramePreview(output, 'startup', generation)" in startup_preview
assert "this.startFramePreview(output, 'after', generation)" in after_preview
assert "GLib.timeout_add(GLib.PRIORITY_DEFAULT, 42" in source
assert "'-vf', 'fps=24,scale=360:360:flags=lanczos'" in source
assert 'picture.set_paintable(textures[index])' in source
assert display.count('can_target: false') >= 4
assert 'startupFrameTimerId' in source
assert 'previewFrameTimerId' in source
assert 'startupPreviewMedia' not in source
assert 'previewMedia' not in source
assert 'this.activePreviewPath' not in startup_preview
assert 'this.startupActivePreviewPath' not in after_preview
assert 'startupPreviewVideo' not in source
assert 'previewVideo' not in source
assert "set_visible_child_name('video')" not in source
assert "set_tooltip_text('Click to choose startup content')" not in source
assert "set_tooltip_text('Click to choose content')" not in source
assert 'LCD Preview' not in display
assert 'Round · 480 × 480' not in display
assert 'Animated content loops in the preview.' not in display
assert 'Image, GIF, or video' not in display

# Each phase owns its picker state. After-login selection must never arm startup actions.
assert 'this.startupSelectedFile' in choose_startup
assert 'this.startupUseButton.set_sensitive(false)' in choose_startup
assert 'this.startupSelectedKind' in inspect_startup
assert 'this.startupUseButton.set_sensitive(true)' in inspect_startup
assert 'startupUseButton' not in choose_after
assert 'startupUseButton' not in inspect_after
assert 'this.startupSelectedFile' in set_startup
assert 'this.startupSelectedKind' in set_startup
assert "'device-start', mode, this.startupSelectedFile" in set_startup
assert '...this.startupTransformArgs()' in set_startup
assert '...this.transformArgs()' not in set_startup
assert 'startupTransformArgs()' in source
assert 'startupRotation' in source
assert 'startupMirrorHorizontalValue' in source
assert 'startupMirrorVerticalValue' in source

# Before-Linux configuration restores the normal after-login display instead of stealing it.
assert 'previousAction = this.lastAction' in set_startup
assert "this.runCli(['restore']" in set_startup
assert 'resumeDashboardAfterStartup' in set_startup
assert 'restoreAfterStartupConfiguration' in set_startup

# After-login is an actual saved phase, with explicit status derived from lastAction.
assert 'updateAfterLoginStatus(config)' in source
assert "action.type === 'image'" in source
assert "action.type === 'remote-media'" in source
assert "action.type === 'dashboard'" in source
assert "action.type === 'stopped'" in source

# Removed UX should not creep back in.
assert 'autoRestore' not in source
assert 'Restore last LCD content after login' not in source
assert 'Restore now' not in source
assert "line.startsWith('frozr-startup-')" in source

# Library populates itself on app startup instead of waiting for a manual refresh.
assert 'this.refreshStatus(true);' in source
assert 'refreshStatus(refreshLibraryOnReady = false)' in source
assert 'if (ok)\n                this.refreshFiles();' in source
assert "this.showFileListMessage('Loading…');" in source
assert "this.showFileListMessage('No uploaded media');" in source

print('GUI phase hierarchy and independence checks passed')
