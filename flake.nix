{
  description = "pyctr";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
  };

  outputs =
    inputs@{ self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "i686-linux"
        "x86_64-darwin"
        "aarch64-darwin"
        "aarch64-linux"
        "armv6l-linux"
        "armv7l-linux"
      ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f system);
    in
    {
      legacyPackages = forAllSystems (
        system:
        (import ./default.nix {
          pkgs = import nixpkgs { inherit system; };
        })
        // {
          default = self.legacyPackages.${system}.pyctr;
        }
      );
      packages = forAllSystems (
        system: nixpkgs.lib.filterAttrs (_: v: nixpkgs.lib.isDerivation v) self.legacyPackages.${system}
      );

      devShells = forAllSystems (
        system:
        let
          pkgs = import nixpkgs { inherit system; };
        in
        {
          default = pkgs.callPackage ./shell.nix { };
          withPyctr = pkgs.callPackage ./shell.nix { withPyctr = true; };
        }
      );
    };
}
