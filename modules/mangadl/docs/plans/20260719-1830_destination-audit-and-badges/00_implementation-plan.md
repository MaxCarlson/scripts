# Destination Audit and Backend Badges

Add colored compact backend markers to worker rows. Add a read-only `audit`
command (with `audit-destinations` compatibility alias)
that accepts multiple URL files and multiple destination roots, writes a URL
file for unresolved items, and writes JSON containing duplicate folder names
and all their locations. Matching must remain conservative and never infer a
download from a merely similar unrelated directory name.

Input-file arguments accept local globs such as `-i "urls*.txt"`. Progress is
visible on stderr during the potentially long destination scan while JSON
summaries remain clean on stdout.
