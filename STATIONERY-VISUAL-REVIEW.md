# Stationery visual correction — approved for v1.7.1

The v1.7.0 stationery was too generic compared with the six approved collection concepts. This revision gives editorial, meadow, colour, botanical, classic and photographic designs distinct compositions and restores their typography, accent ampersands, artwork scale, monograms and course spacing. It adds a local italic font and an original transparent meadow frame. Printed text remains editable and embedded in the PDF.

The actual renderer produces the review images; these are not generated mockups of what a later implementation might look like. They use fictional Emma & Jamie sample details. Photo Story shows a labelled photo placeholder until a couple supplies their own photo. Production includes no fictional couple photograph.

This review changes the renderer, local stationery artwork/fonts and tests only. Existing routes, forms, drafts, guest batches, permissions, backups, payment settings and booking integrations remain in place. There is no migration or draft rewrite. Saved wording is retained; any new download uses the revised composition and must still be checked before sharing or printing.

Mark approved the actual renderer output on 24 October 2026. Version 1.7.1 retains those exact templates. Deployment uses scripts/deploy-v171.sh; publishing the source does not itself update the TrueNAS installation.

Validation: render every collection/item pair; inspect collection contact sheets and individual layouts; verify all offered paper sizes and text within the trim, large contrasting name treatments, embedded PDF/PNG output, plus the existing stationery permission/save/conflict/export/backup tests. Standard long-word and unsupported-character checks still block unsafe output rather than clipping wording.
