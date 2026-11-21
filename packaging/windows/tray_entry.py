from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from posvirtual.tray_agent import main

raise SystemExit(main())
