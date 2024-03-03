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
          pyfatfs = pkgs.python3Packages.callPackage ./pyfatfs.nix { };
          pyctr = pkgs.python3Packages.callPackage ./pyctr.nix { pyfatfs = self.packages.${system}.pyfatfs; };
          default = pyctr;
        };
      }
    );
}
