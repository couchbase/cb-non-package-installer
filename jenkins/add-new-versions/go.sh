#!/bin/bash -e

uv run add_new_versions.py

if [ ! -z "$(git status --porcelain)" ]; then
  if [ "$1" == "--push" ]; then
    f="$(git rev-parse --git-dir)/hooks/commit-msg"; curl -o "$f" https://review.couchbase.org/tools/hooks/commit-msg ; chmod +x "$f" && git config --local core.hooksPath "$(git rev-parse --git-dir)/hooks"
    git remote add gerrit ssh://${GERRIT_USER}@review.couchbase.org:29418/cb-non-package-installer || true
    git commit -am "Update SUPPORTED_VERSIONS_LIST with missing versions"
    git push gerrit HEAD:refs/for/master
    echo
    echo "Changes have been pushed to Gerrit."
    echo
    echo "Please review the changes at https://review.couchbase.org"
    echo "Once merged, the normal manifest build process will trigger https://server.jenkins.couchbase.com/job/python-tool-build/ to complete the build"
    echo "After the build is complete, release the new version using https://server.jenkins.couchbase.com/job/cb-non-package-installer-release/"
    exit 1
  else
    echo "Changes detected but not pushing. Run with --push to submit to Gerrit."
  fi
else
  echo "No changes detected."
fi