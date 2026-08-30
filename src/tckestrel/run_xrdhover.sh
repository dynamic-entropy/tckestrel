#!/bin/bash
# CMS Connect-style wrapper (test.jdl -C CMSSW_…): cmsenv, then exec xrdhover.
set -euo pipefail

CMSSW="${CMSSW:-CMSSW_20_1_0_pre2}"
while [ $# -gt 0 ]; do
  case "$1" in
    -C|--cmssw)
      CMSSW="$2"
      shift 2
      ;;
    --)
      shift
      break
      ;;
    *)
      break
      ;;
  esac
done

SANDBOX=$(pwd)
XRDHOVER="${SANDBOX}/xrdhover"

if [ ! -f /cvmfs/cms.cern.ch/cmsset_default.sh ]; then
  echo "tckestrel: /cvmfs/cms.cern.ch/cmsset_default.sh is missing" >&2
  exit 2
fi
# shellcheck disable=SC1091
source /cvmfs/cms.cern.ch/cmsset_default.sh

if [ -z "${SCRAM_ARCH:-}" ]; then
  cpu=amd64
  [ "$(uname -m)" = aarch64 ] && cpu=aarch64
  ver=""
  if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    ver="${VERSION_ID%%.*}"
  fi
  if [ "$ver" = 9 ]; then
    export SCRAM_ARCH="el9_${cpu}_gcc13"
  else
    export SCRAM_ARCH="el8_${cpu}_gcc13"
  fi
fi

rel=""
for cand in \
  "/cvmfs/cms.cern.ch/${SCRAM_ARCH}/cms/cmssw/${CMSSW}" \
  "/cvmfs/cms.cern.ch/${SCRAM_ARCH}/cms/cmssw-patch/${CMSSW}"; do
  if [ -d "$cand" ]; then
    rel=$cand
    break
  fi
done
if [ -z "$rel" ]; then
  for cand in /cvmfs/cms.cern.ch/*/cms/cmssw/"${CMSSW}" \
    /cvmfs/cms.cern.ch/*/cms/cmssw-patch/"${CMSSW}"; do
    if [ -d "$cand" ]; then
      rel=$cand
      SCRAM_ARCH=$(echo "$cand" | awk -F/ '{print $4}')
      export SCRAM_ARCH
      break
    fi
  done
fi

if [ -n "$rel" ]; then
  cd "$rel"
  eval "$(scramv1 runtime -sh)"
else
  echo "tckestrel: cmsrel ${CMSSW} (SCRAM_ARCH=${SCRAM_ARCH})" >&2
  cd "$SANDBOX"
  scramv1 project CMSSW "$CMSSW"
  cd "${CMSSW}/src"
  eval "$(scramv1 runtime -sh)"
fi

cd "$SANDBOX"
if [ ! -x "$XRDHOVER" ]; then
  echo "tckestrel: xrdhover is not in the sandbox" >&2
  exit 2
fi
exec "$XRDHOVER" "$@"
