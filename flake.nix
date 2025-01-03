{
  description = "pyctr";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = inputs@{ self, nixpkgs, flake-utils }: 

    flake-utils.lib.eachDefaultSystem (system:
      let pkgs = import nixpkgs { inherit system; }; in {

        packages = rec {
          pyfatfs = pkgs.python3Packages.callPackage ./nix/pyfatfs.nix { };
          pyctr = pkgs.python3Packages.callPackage ./package.nix { pyfatfs = self.packages.${system}.pyfatfs; };
          default = pyctr;
          # mainly useful for things like pycharm
          python-environment = pkgs.python3Packages.python.buildEnv.override {
            extraLibs = pyctr.propagatedBuildInputs ++ (with pkgs.python3Packages; [ pytest ]);
            ignoreCollisions = true;
          };
          tester = pkgs.writeShellScriptBin "pyctr-tester" (with self.packages.${system}; ''
            PYTHONPATH=$PWD:$PYTHONPATH ${python-environment}/bin/pytest ./tests
          '');
        };

        devShells.default = pkgs.callPackage ./shell.nix {};
      }
    );
}
