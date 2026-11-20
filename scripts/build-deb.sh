#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="${1:-dist}"
if [[ "$output_dir" != /* ]]; then
  output_dir="$repo_root/$output_dir"
fi

cd "$repo_root"
version="$(dpkg-parsechangelog -S Version)"
package_name="posvirtual_${version}_all.deb"
built_package="$repo_root/../$package_name"

mkdir -p "$output_dir"
dpkg-buildpackage -us -uc -b
if [[ ! -s "$built_package" ]]; then
  echo "Pacote Debian não encontrado após o build: $built_package" >&2
  exit 1
fi

if [[ "$(dpkg-deb -f "$built_package" Package)" != "posvirtual" ||
      "$(dpkg-deb -f "$built_package" Version)" != "$version" ||
      "$(dpkg-deb -f "$built_package" Architecture)" != "all" ]]; then
  echo "Metadados do pacote Debian não correspondem ao changelog" >&2
  exit 1
fi

install -m 0644 "$built_package" "$output_dir/$package_name"
(
  cd "$output_dir"
  sha256sum "$package_name" > "$package_name.sha256"
)

printf 'Pacote: %s\nChecksum: %s\n' "$output_dir/$package_name" "$output_dir/$package_name.sha256"
