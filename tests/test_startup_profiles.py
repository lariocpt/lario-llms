import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class StartupProfileTests(unittest.TestCase):
    def run_startup(self, enabled=False, invalid=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'start_all.sh').write_text((ROOT/'start_all.sh').read_text())
            for name in ('bin','shared','intel','rtx5080/config','rtx5080/systemd',
                         '7900xt','llama-cpp','home/.config/systemd/user'):
                (root/name).mkdir(parents=True,exist_ok=True)
            (root/'rtx5080/config/generated.yaml').write_text('fixture')
            (root/'shared/compose-files.sh').write_text('lario_compose_files() { LARIO_COMPOSE_FILES=(); }\n')
            def executable(name,text):
                path = root/name;path.write_text('#!/usr/bin/env bash\n'+text);path.chmod(0o755)
            executable('intel/install.sh','exit 0\n')
            executable('bin/hostname','printf "bigcachy\\n"\n')
            for name in ('systemctl','install'):executable('bin/'+name,'exit 0\n')
            executable('7900xt/7900xt','printf "radeon-config\\n" >> "$TEST_LOG"\n')
            executable('bin/docker','''if [[ " $* " == *" config --services "* ]]; then
  [[ "${TEST_INVALID:-0}" == 0 ]] || exit 23
  printf "chromadb\\nrag_api\\nvision\\n"
  [[ "${TEST_XT:-0}" == 0 ]] || printf "agent-llm\\n"
  exit 0
fi
printf 'docker %s\\n' "$*" >> "$TEST_LOG"
''')
            env={**os.environ,'HOME':str(root/'home'),'PATH':str(root/'bin')+':'+os.environ['PATH'],
                 'TEST_LOG':str(root/'calls'),'TEST_XT':str(int(enabled)),
                 'TEST_INVALID':str(int(invalid))}
            result=subprocess.run(['bash',str(root/'start_all.sh')],env=env,capture_output=True,text=True)
            calls=(root/'calls').read_text() if (root/'calls').exists() else ''
            return result.returncode,calls

    def test_disabled_radeon_is_never_named_or_force_enabled(self):
        code,calls=self.run_startup()
        self.assertEqual(code,0)
        self.assertNotIn('agent-llm',calls)
        self.assertNotIn('radeon-config',calls)
        self.assertNotIn('--profile',calls)
        self.assertIn('up -d chromadb rag_api vision',calls)

    def test_enabled_profile_still_starts_radeon(self):
        code,calls=self.run_startup(enabled=True)
        self.assertEqual(code,0)
        self.assertIn('radeon-config',calls)
        self.assertIn('agent-llm',calls)
        self.assertNotIn('--profile',calls)

    def test_invalid_compose_configuration_cannot_trigger_stack_start(self):
        code,calls=self.run_startup(invalid=True)
        self.assertNotEqual(code,0)
        self.assertEqual(calls,'')


if __name__=='__main__':unittest.main()
