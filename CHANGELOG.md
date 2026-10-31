# Changelog

Notable changes to Award Wallet. Versions follow [semantic versioning](https://semver.org).

## [Unreleased]

### Added
- One-click updates: the app checks for a new version on launch, then downloads it, replaces
  itself and reopens.
- `release.sh` publishes a new version with one command.

## [0.3.0] - 2026-10-31

### Added
- Automatic balances for United, Chase and Capital One. Award Wallet signs in through Google
  Chrome with your saved login and reads the balance. The first time, a Chrome window opens so you
  can enter the site's security code; after that the browser is remembered and refreshes run
  quietly.
- Balances refresh every time the app opens, plus a Refresh now button on the dashboard.
- A program that needs you (a security code, or a changed password) says so and offers a Sign in
  button instead of retrying in the background.

## [0.2.0] - 2026-10-31

### Added
- Mac app: Award Wallet opens in its own window from Applications, with no Terminal and no
  sign-in screen. Data lives in `~/Library/Application Support/Award Wallet`.
- Wallet app icon.
- About page and Check for Updates, in the Award Wallet and Help menus.
- A link from each program to its rewards site, to plan trips and transfer points.
- Makefile, lint (ruff), CI and a release workflow that builds the .dmg.

## [0.1.0] - 2026-10-26

### Added
- Accounts, encrypted program logins and manual balances for United MileagePlus, Chase Ultimate
  Rewards and Capital One Miles.
