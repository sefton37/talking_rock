{
  description = "ReOS - Local-first, Git-first attention kernel companion";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    rust-overlay = {
      url = "github:oxalica/rust-overlay";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, flake-utils, rust-overlay }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        overlays = [ (import rust-overlay) ];
        pkgs = import nixpkgs {
          inherit system overlays;
        };

        # Rust toolchain
        rustToolchain = pkgs.rust-bin.stable.latest.default.override {
          extensions = [ "rust-src" "rust-analyzer" ];
        };

        # Python environment
        pythonEnv = pkgs.python312.withPackages (ps: with ps; [
          fastapi
          httpx
          uvicorn
          pydantic
          # Dev dependencies
          pytest
          mypy
          ruff
          # For CLI
          typer
          rich
        ]);

        # Native build inputs for Tauri
        nativeBuildInputs = with pkgs; [
          pkg-config
          rustToolchain
          cargo
          nodejs_20
          nodePackages.npm
        ];

        # Build inputs for Tauri on Linux
        buildInputs = with pkgs; [
          # Tauri dependencies
          webkitgtk
          gtk3
          cairo
          gdk-pixbuf
          glib
          dbus
          openssl
          librsvg
          libappindicator-gtk3

          # For notifications
          libnotify

          # SQLite
          sqlite
        ];

        # Library path for runtime
        libPath = pkgs.lib.makeLibraryPath buildInputs;

      in
      {
        # Development shell
        devShells.default = pkgs.mkShell {
          inherit nativeBuildInputs buildInputs;

          packages = with pkgs; [
            pythonEnv
            git
            just
            pre-commit
            watchexec
            sqlite

            # Optional: Local LLM
            # ollama
          ];

          shellHook = ''
            export LD_LIBRARY_PATH="${libPath}:$LD_LIBRARY_PATH"
            export REOS_LOG_LEVEL="DEBUG"

            # Create venv if it doesn't exist
            if [ ! -d ".venv" ]; then
              echo "Creating Python virtual environment..."
              python -m venv .venv
              .venv/bin/pip install -e ".[dev]"
            fi

            # Activate venv
            source .venv/bin/activate

            echo "ReOS development environment ready!"
            echo "Run 'just dev' to start the Tauri development server"
          '';
        };

        # Python package
        packages.reos = pkgs.python312Packages.buildPythonPackage {
          pname = "reos";
          version = "0.0.0a0";
          src = ./.;
          format = "pyproject";

          nativeBuildInputs = with pkgs.python312Packages; [
            setuptools
            wheel
          ];

          propagatedBuildInputs = with pkgs.python312Packages; [
            fastapi
            httpx
            uvicorn
            pydantic
            typer
            rich
          ];

          doCheck = false; # Tests require Ollama
        };

        # Tauri desktop app
        packages.reos-desktop = pkgs.rustPlatform.buildRustPackage {
          pname = "reos-desktop";
          version = "0.0.0";
          src = ./apps/reos-tauri/src-tauri;

          cargoLock = {
            lockFile = ./apps/reos-tauri/src-tauri/Cargo.lock;
          };

          inherit nativeBuildInputs buildInputs;

          # Copy frontend dist
          preBuild = ''
            cd ${./apps/reos-tauri}
            npm ci
            npm run build
            cd src-tauri
          '';

          postInstall = ''
            # Install desktop file
            install -Dm644 ${./dist/reos.desktop} $out/share/applications/reos.desktop

            # Install man page
            install -Dm644 ${./dist/reos.1} $out/share/man/man1/reos.1
          '';
        };

        # Default package
        packages.default = self.packages.${system}.reos-desktop;

        # NixOS module
        nixosModules.default = { config, lib, pkgs, ... }:
          with lib;
          let
            cfg = config.services.reos;
          in
          {
            options.services.reos = {
              enable = mkEnableOption "ReOS attention kernel";

              package = mkOption {
                type = types.package;
                default = self.packages.${system}.reos;
                description = "The ReOS package to use";
              };

              user = mkOption {
                type = types.str;
                default = "reos";
                description = "User to run ReOS as";
              };

              logLevel = mkOption {
                type = types.enum [ "DEBUG" "INFO" "WARNING" "ERROR" ];
                default = "INFO";
                description = "Log level";
              };

              ollamaUrl = mkOption {
                type = types.str;
                default = "http://127.0.0.1:11434";
                description = "Ollama endpoint URL";
              };
            };

            config = mkIf cfg.enable {
              systemd.user.services.reos = {
                description = "ReOS Attention Kernel";
                wantedBy = [ "default.target" ];
                after = [ "network.target" ];

                environment = {
                  REOS_LOG_LEVEL = cfg.logLevel;
                  REOS_OLLAMA_URL = cfg.ollamaUrl;
                };

                serviceConfig = {
                  ExecStart = "${cfg.package}/bin/reos kernel";
                  Restart = "on-failure";
                  RestartSec = 5;
                };
              };
            };
          };

        # Overlay for other flakes
        overlays.default = final: prev: {
          reos = self.packages.${system}.reos;
          reos-desktop = self.packages.${system}.reos-desktop;
        };
      }
    );
}
