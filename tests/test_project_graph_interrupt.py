"""F6: el grafo de proyecto NO usa interrupt_before estático (rompía cli.py con IndexError).

Los checkpoints humanos (human_approve_roadmap, present_suggestions) suspenden con
`interrupt()` dinámico, que entrega payload al stream. Un `interrupt_before` estático
emite `{"__interrupt__": ()}` vacío en langgraph 1.x → cli.py hacía node_output[0].value
sobre tupla vacía → IndexError. Este test fija que no regrese.
"""
import inspect

import graph_project as gp


def test_compile_project_graph_has_no_static_interrupt_before():
    app = gp.compile_project_graph()
    # langgraph expone los nodos con interrupt_before estático; debe estar vacío.
    nodes = getattr(app, "interrupt_before_nodes", [])
    assert list(nodes) == [], f"interrupt_before debe estar vacío, fue: {nodes}"


def test_human_checkpoints_use_dynamic_interrupt():
    # Los nodos de checkpoint humano deben llamar a interrupt() dinámico.
    for fn in (gp.human_approve_roadmap, gp.present_suggestions):
        src = inspect.getsource(fn)
        assert "interrupt(" in src, f"{fn.__name__} debe usar interrupt() dinámico"
