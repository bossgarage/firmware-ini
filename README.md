# BossECU firmware INI files

This repository stores TunerStudio INI definitions generated for BossECU boards based on EpicEFI / rusEFI.

## Boards

- `BossECU_48`
- `BossECU_Brain_F4`
- `BosssECU_Brain_H7`

Files are named with the upstream rusEFI revision date and build identifier where available. Multiple dated files are retained as snapshots so firmware and project definitions can be matched to the right version.

Use the INI file that matches the firmware installed on your ECU. Loading a mismatched definition may expose incorrect settings or data fields.