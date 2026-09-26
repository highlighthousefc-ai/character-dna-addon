# 02: Backup Manager

**Depends on:** 01 (commit hooks, `dna_io`).

## Purpose
Automatically snapshot the `.dna` file(s) around every point where DNA could change, and let the user roll back.

## Behavior

### Automatic backup events
Take a snapshot at each of these:
- Blender file saved
- Before and after each **Raw Editor** commit
- Before and after each **Raw Editor rest-pose** commit
- Before and after each **RBF Editor** commit
- Before and after each **Shape Key Editor** commit
- Manual backup (user clicks **Add**, with a description)

Taking both a "pre" and "post" snapshot lets the user roll back to either side of any change.

### Backup list panel
- Each entry: timestamp, description, type (e.g. pre-commit, post-commit, manual, file-saved).
- Buttons: **Refresh** (rescan folder), **Open Folder**, **Add** (manual backup), **Restore**, **Delete**.

### Restore
User picks what to bring back: reimport **meshes**, **bones**, and/or **shape keys**. Restoring must leave the scene and DNA consistent.

### Preferences
- Enable automatic backups (master switch; manual backups always work).
- Backup folder (default: system temp dir; support absolute paths and Blender `//` relative paths).
- Max automatic backups to keep **per rig instance**; delete the oldest automatic ones beyond this. **Never** auto-delete manual backups.

## Implementation notes
- Subscribe to the pre/post-commit hooks from the foundation; editors must not know the backup manager exists.
- Backups are copies of the DNA file(s) plus a small metadata sidecar (timestamp, description, type, rig instance id). Choose a naming scheme that sorts chronologically.
- Copy atomically (write to temp, then rename) to avoid half-written backups if Blender crashes.

## Acceptance criteria
- Committing an edit in any editor produces a pre and post backup, in order.
- Restoring a pre-commit backup reproduces the earlier DNA data exactly (compare programmatically).
- Retention deletes only automatic backups, per rig instance, oldest first.
- Turning auto backups off stops new automatic backups but manual ones still work.
