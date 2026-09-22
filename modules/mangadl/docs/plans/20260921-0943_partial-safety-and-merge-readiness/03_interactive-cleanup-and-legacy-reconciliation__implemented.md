# Stage S4 - Interactive Cleanup and Legacy Reconciliation

`mangadl partials clean` opens a TermDash tree when no target is supplied. It
supports nested browsing, hierarchical sort, URL/ownership detail, and
multi-select only for top-level partial owners.

Legacy owner URLs are recovered from local state databases or validated URL
overrides. Gallery-dl enumerates archive keys through a temporary empty archive
and `--print`, without downloading media. Exact matching rows in the explicit
archive are backed up and removed before deletion.

Active gallery-dl command lines, recent activity when process inspection is
unavailable, partial-subtree legacy selection, unresolved/ambiguous URLs, and
empty key reconstruction all refuse cleanup. Apply also fingerprints the target
again before changing the archive.

Verification: focused tests plus full module suite and repository dispatcher.
