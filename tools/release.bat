@echo off
setlocal enabledelayedexpansion

REM ===========================================================================
REM  Publish a public release of OscGoesPurrr.
REM
REM  Builds the frozen exe, tags the commit, and creates the GitHub release
REM  with the exe attached -- which is what the in-app updater downloads.
REM
REM  The version is NOT passed in: it comes from VERSION in version.py, so
REM  there is exactly one place to bump and the tag can never disagree with
REM  what the app reports about itself (the update check compares the two).
REM
REM  Usage:
REM      1. Edit VERSION in src\version.py          (e.g. "0.9.1")
REM      2. Commit that on release/lite
REM      3. tools\release.bat
REM
REM  release.bat --fresh-history   publishes this release as the public
REM  repo's first commit instead of stacking it on the previous one, and
REM  replaces main with it (force-with-lease). Only for starting the public
REM  history over -- every copy's "update available" still works, since the
REM  updater reads releases, not commits.
REM
REM  Needs the GitHub CLI (https://cli.github.com/) authenticated with
REM  `gh auth login`.
REM ===========================================================================

cd /d "%~dp0.."

echo ========================================
echo   OscGoesPurrr - Publish a release
echo ========================================
echo.

set "VENV_PY=venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo [ERROR] No venv found. Run build_OGP.bat once first - it creates one.
    pause
    exit /b 1
)

REM ---- Which remote and branch a public release comes from. The updater
REM ---- asks api.github.com for the latest release of PUBLIC_REPO, so the
REM ---- release has to land there and nowhere else.
set "PUBLIC_REMOTE=public"
set "PUBLIC_REPO=Blise518B/OscGoesPurrr"
set "RELEASE_BRANCH=release/lite"
REM GitHub's noreply address for the account. Every public commit and tag
REM is authored with this, whatever user.email this machine has.
set "PUBLIC_EMAIL=43812951+Blise518B@users.noreply.github.com"

set "FRESH="
if /i "%~1"=="--fresh-history" set "FRESH=1"

REM ---- 1. Refuse to release from a dirty tree. A release built from
REM ---- uncommitted work cannot be reproduced from its own tag.
for /f "usebackq tokens=*" %%i in (`git status --porcelain --untracked-files^=no`) do (
    echo [ERROR] Working tree has uncommitted changes:
    git status --short --untracked-files=no
    echo.
    echo         Commit or stash them first - a release must be reproducible
    echo         from the tag it carries.
    pause
    exit /b 1
)

REM ---- 2. Confirm the branch.
for /f "usebackq tokens=*" %%i in (`git rev-parse --abbrev-ref HEAD`) do set "BRANCH=%%i"
if not "!BRANCH!"=="%RELEASE_BRANCH%" (
    echo [WARNING] You are on "!BRANCH!", not "%RELEASE_BRANCH%".
    echo           The version string will carry a branch suffix and the
    echo           update check will not match it to the tag.
    set /p CONFIRM="Continue anyway? (y/N) "
    if /i not "!CONFIRM!"=="y" exit /b 1
)

REM ---- 3. Read the version. This is the single source of truth.
for /f "usebackq tokens=*" %%i in (`%VENV_PY% -c "import sys; sys.path.insert(0, 'src'); from version import VERSION; print(VERSION)"`) do set "REL_VERSION=%%i"
if not defined REL_VERSION (
    echo [ERROR] Could not read VERSION from version.py.
    pause
    exit /b 1
)
set "TAG=v!REL_VERSION!"
echo Releasing: !TAG!
echo.

REM ---- 4. Refuse to reuse a tag. Re-tagging a published release silently
REM ---- changes what users downloaded under that name.
git rev-parse -q --verify "refs/tags/!TAG!" >nul 2>&1
if not errorlevel 1 (
    echo [ERROR] Tag !TAG! already exists locally.
    echo         Bump VERSION in version.py for a new release.
    pause
    exit /b 1
)
gh release view "!TAG!" --repo "%PUBLIC_REPO%" >nul 2>&1
if not errorlevel 1 (
    echo [ERROR] Release !TAG! already exists on %PUBLIC_REPO%.
    echo         Bump VERSION in version.py for a new release.
    pause
    exit /b 1
)

REM ---- 5. Tests must pass. A release is the one build a stranger runs.
echo [1/5] Running the test suite...
"%VENV_PY%" -m pytest -q
if errorlevel 1 (
    echo.
    echo [ERROR] Tests failed - not releasing.
    pause
    exit /b 1
)
echo.

REM ---- 6. Build. build_OGP.bat names the exe from the same version.py.
echo [2/5] Building the frozen exe...
call "%~dp0build_OGP.bat"
if errorlevel 1 (
    echo [ERROR] Build failed - not releasing.
    pause
    exit /b 1
)

set "EXE=dist\OscGoesPurrr_!REL_VERSION!.exe"
if not exist "!EXE!" (
    echo [ERROR] Expected !EXE! but it is not there.
    echo         Check the build output above.
    pause
    exit /b 1
)
echo.
echo [3/5] Built: !EXE!

REM ---- 7. Publish ONE squashed commit, never this branch's history.
REM ----
REM ---- The public repo gets a single commit per release whose files are
REM ---- exactly this commit's files, stacked on the previous public release.
REM ---- The development history stays in the private repo: it carries the
REM ---- maintainer's personal email on every commit and the full history of
REM ---- the backends this edition deliberately leaves out. git commit-tree
REM ---- builds that commit without touching this branch or the worktree.
REM ----
REM ---- The identity is pinned here, not taken from git config, so a
REM ---- machine with a personal user.email can never leak it into a release.
echo [4/5] Building the public commit and pushing...
set "GIT_AUTHOR_NAME=Blise518B"
set "GIT_AUTHOR_EMAIL=%PUBLIC_EMAIL%"
set "GIT_COMMITTER_NAME=Blise518B"
set "GIT_COMMITTER_EMAIL=%PUBLIC_EMAIL%"

git fetch -q "%PUBLIC_REMOTE%"
if errorlevel 1 (
    echo [ERROR] Could not fetch %PUBLIC_REMOTE%.
    pause
    exit /b 1
)
REM %%T is the tree hash (written %%T because this is a batch file).
for /f "usebackq tokens=*" %%i in (`git log -1 --format^=%%T HEAD`) do set "TREE=%%i"
set "PARENT="
set "OLDMAIN="
git rev-parse -q --verify "refs/remotes/%PUBLIC_REMOTE%/main" >nul 2>&1
if not errorlevel 1 (
    for /f "usebackq tokens=*" %%i in (`git rev-parse "refs/remotes/%PUBLIC_REMOTE%/main"`) do set "OLDMAIN=%%i"
    if not defined FRESH set "PARENT=-p %PUBLIC_REMOTE%/main"
)
if defined FRESH echo Fresh history: this release becomes the public repo's first commit.
set "PUBCOMMIT="
for /f "usebackq tokens=*" %%i in (`git commit-tree !TREE! !PARENT! -m "OscGoesPurrr !TAG!"`) do set "PUBCOMMIT=%%i"
if not defined PUBCOMMIT (
    echo [ERROR] Could not build the public commit.
    pause
    exit /b 1
)
echo Public commit: !PUBCOMMIT!

git tag -a "!TAG!" "!PUBCOMMIT!" -m "OscGoesPurrr !TAG!"
if errorlevel 1 (
    echo [ERROR] Could not create tag !TAG!.
    pause
    exit /b 1
)
if defined FRESH (
    REM Replace main, but only if it is still what we just fetched.
    git push --force-with-lease=refs/heads/main:!OLDMAIN! "%PUBLIC_REMOTE%" "!PUBCOMMIT!:refs/heads/main"
) else (
    git push "%PUBLIC_REMOTE%" "!PUBCOMMIT!:refs/heads/main"
)
if errorlevel 1 (
    echo [ERROR] Could not push to %PUBLIC_REMOTE%. The tag exists locally;
    echo         delete it with: git tag -d !TAG!
    pause
    exit /b 1
)
git push "%PUBLIC_REMOTE%" "!TAG!"
if errorlevel 1 (
    echo [ERROR] Could not push the tag.
    pause
    exit /b 1
)

REM ---- 8. Create the release with the exe attached. The attached .exe is
REM ---- what updater.pick_exe_asset looks for -- without it the in-app
REM ---- updater can only send people to the page.
echo [5/5] Creating the GitHub release...
REM The asset is uploaded under ONE stable name, never a versioned one:
REM the README's big Download button links to
REM releases/latest/download/OscGoesPurrr-Windows.exe, which only resolves
REM while every release carries exactly that file. The updater accepts it
REM (updater.pick_exe_asset matches any *oscgoespurrr*.exe).
set "ASSET=dist\OscGoesPurrr-Windows.exe"
copy /Y "!EXE!" "!ASSET!" >nul
if errorlevel 1 (
    echo [ERROR] Could not copy !EXE! to !ASSET!.
    pause
    exit /b 1
)
gh release create "!TAG!" "!ASSET!" ^
    --repo "%PUBLIC_REPO%" ^
    --title "OscGoesPurrr !TAG!" ^
    --notes-file "tools\RELEASE_NOTES.md"
if errorlevel 1 (
    echo [ERROR] gh release create failed. The tag is pushed; you can retry
    echo         just this step, or create the release from the web UI and
    echo         attach !ASSET! yourself.
    pause
    exit /b 1
)

echo.
echo ========================================
echo   Released !TAG!
echo ========================================
echo.
echo   https://github.com/%PUBLIC_REPO%/releases/tag/!TAG!
echo.
echo Every copy already out there will offer this update at next launch.
echo.
pause
endlocal
