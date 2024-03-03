{
  description = "pyctr";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = inputs@{ self, nixpkgs, flake-utils }: 

    flake-utils.lib.eachDefaultSystem (system:
      let pkgs = nixpkgs.legacyPackages.${system}; in {

        packages = rec {
          pyctr = pkgs.python3Packages.callPackage ./pyctr.nix { };
          default = pyctr;
        };
      }
    );
}
