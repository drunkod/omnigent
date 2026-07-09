{
  description = "Omnigent development shell and test runners";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs {
          inherit system;
        };

        python = pkgs.python312;

        uvEnv = ''
          export UV_PYTHON=${python}/bin/python3.12
          export UV_PYTHON_DOWNLOADS=never
          export UV_PROJECT_ENVIRONMENT=.venv
        '';

        mkUvApp =
          name: command:
          {
            type = "app";
            program = pkgs.writeShellScript name ''
              set -eu
              ${uvEnv}
              ${command} "$@"
            '';
          };
      in
      {
        formatter = pkgs.nixfmt-rfc-style;

        devShells.default = pkgs.mkShell {
          packages = [
            python
            pkgs.uv
            pkgs.git
            pkgs.nodejs_22
            pkgs.tmux
          ];

          shellHook = ''
            ${uvEnv}
            echo "Omnigent dev shell ready."
            echo "First run: uv sync --frozen --extra dev"
            echo "Then tests: uv run --frozen --extra dev python -m pytest tests/runner/ tests/runner/transports/ws_tunnel/"
          '';
        };

        apps = {
          sync = mkUvApp "omnigent-uv-sync" ''
            exec ${pkgs.uv}/bin/uv sync --frozen --extra dev
          '';

          test = mkUvApp "omnigent-test" ''
            exec ${pkgs.uv}/bin/uv run --frozen --extra dev python -m pytest
          '';

          test-runner = mkUvApp "omnigent-test-runner" ''
            exec ${pkgs.uv}/bin/uv run --frozen --extra dev python -m pytest \
              tests/runner/ \
              tests/runner/transports/ws_tunnel/
          '';

          pre-commit = mkUvApp "omnigent-pre-commit" ''
            exec ${pkgs.uv}/bin/uv run --frozen --extra dev pre-commit run --all-files
          '';
        };
      }
    );
}
