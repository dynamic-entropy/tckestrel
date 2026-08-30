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

cpu=amd64
[ "$(uname -m)" = aarch64 ] && cpu=aarch64
host_os=el8
if [ -r /etc/os-release ]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  case "${VERSION_ID%%.*}" in
    9) host_os=el9 ;;
    10) host_os=el10 ;;
  esac
fi
# cmsset_default.sh usually sets SCRAM_ARCH to el8. Ignore it when it
# does not match the glidein OS (el8 CMSSW on el9 → missing libssl.so.1.1).
case "${SCRAM_ARCH:-}" in
  "${host_os}_"*) ;;
  *) unset SCRAM_ARCH ;;
esac

pick_release() {
  local arch="$1"
  local cand
  for cand in \
    "/cvmfs/cms.cern.ch/${arch}/cms/cmssw/${CMSSW}" \
    "/cvmfs/cms.cern.ch/${arch}/cms/cmssw-patch/${CMSSW}"; do
    if [ -d "$cand" ]; then
      printf '%s' "$cand"
      return 0
    fi
  done
  return 1
}

rel=""
if [ -n "${SCRAM_ARCH:-}" ]; then
  rel=$(pick_release "$SCRAM_ARCH" || true)
fi
if [ -z "$rel" ]; then
  for gcc in gcc14 gcc13 gcc12; do
    SCRAM_ARCH="${host_os}_${cpu}_${gcc}"
    rel=$(pick_release "$SCRAM_ARCH" || true)
    [ -n "$rel" ] && break
  done
fi
if [ -z "$rel" ]; then
  for cand in /cvmfs/cms.cern.ch/"${host_os}"_*/cms/cmssw/"${CMSSW}" \
    /cvmfs/cms.cern.ch/"${host_os}"_*/cms/cmssw-patch/"${CMSSW}"; do
    if [ -d "$cand" ]; then
      rel=$cand
      SCRAM_ARCH=$(echo "$cand" | awk -F/ '{print $4}')
      break
    fi
  done
fi
export SCRAM_ARCH="${SCRAM_ARCH:-}"

if [ -n "$rel" ]; then
  echo "tckestrel: cmsenv ${rel} (SCRAM_ARCH=${SCRAM_ARCH} host=${host_os})" >&2
  cd "$rel"
  eval "$(scramv1 runtime -sh)"
else
  echo "tckestrel: cmsrel ${CMSSW} (SCRAM_ARCH=${SCRAM_ARCH:-unset} host=${host_os})" >&2
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
