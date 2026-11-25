# BossECU firmware INI files

This repository stores TunerStudio INI definitions generated for BossECU boards based on EpicEFI / rusEFI.

## Boards

- `BossECU_48`
- `BossECU_Brain_F4`
- `BossECU_Brain_H7`

Files are named with the upstream rusEFI revision date and build identifier where available. Multiple dated files are retained as snapshots so firmware and project definitions can be matched to the right version.

Use the INI file that matches the firmware installed on your ECU. Loading a mismatched definition may expose incorrect settings or data fields.

## Automatic updates

GitHub Actions checks the public [EpicEFI firmware index](https://www.epicefi.com/firmware/fw.php/) daily at 08:00 GMT. It imports every dated snapshot newer than the latest INI already stored for each board, keeps earlier snapshots, and commits all newly found INIs directly to `main` in one commit. The filename is taken from the INI's `signature` value. If the listing or signature is ambiguous, the run stops without committing.

Run the workflow manually from the Actions tab with **Update firmware INI snapshots**.
