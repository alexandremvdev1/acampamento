from django.db import migrations, models
import django.db.models.deletion

SQL_ADD_ATIVO = """
ALTER TABLE inscricoes_ministerio
ADD COLUMN IF NOT EXISTS ativo boolean NOT NULL DEFAULT true;
"""

SQL_ADD_EVENTO_COL = """
ALTER TABLE inscricoes_alocacaogrupo
ADD COLUMN IF NOT EXISTS evento_id uuid;
"""

SQL_POPULAR_EVENTO = """
UPDATE inscricoes_alocacaogrupo ag
SET evento_id = i.evento_id
FROM inscricoes_inscricao i
WHERE ag.inscricao_id = i.id AND ag.evento_id IS NULL;
"""

SQL_SET_NOT_NULL = """
DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_name = 'inscricoes_alocacaogrupo'
      AND column_name = 'evento_id'
  ) THEN
    IF NOT EXISTS (SELECT 1 FROM inscricoes_alocacaogrupo WHERE evento_id IS NULL) THEN
      ALTER TABLE inscricoes_alocacaogrupo
      ALTER COLUMN evento_id SET NOT NULL;
    END IF;
  END IF;
END $$;
"""

SQL_ADD_FK = """
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.table_constraints tc
    WHERE tc.table_name = 'inscricoes_alocacaogrupo'
      AND tc.constraint_type = 'FOREIGN KEY'
      AND tc.constraint_name = 'insc_alocagrupo_evento_fk'
  ) THEN
    ALTER TABLE inscricoes_alocacaogrupo
      ADD CONSTRAINT insc_alocagrupo_evento_fk
      FOREIGN KEY (evento_id)
      REFERENCES inscricoes_eventoacampamento (id)
      ON DELETE CASCADE;
  END IF;
END $$;
"""

SQL_ADD_INDEX = """
CREATE INDEX IF NOT EXISTS alocgrupo_evento_idx
  ON inscricoes_alocacaogrupo (evento_id);
"""

def copy_evento_from_inscricao(apps, schema_editor):
    with schema_editor.connection.cursor() as cur:
        cur.execute(SQL_POPULAR_EVENTO)

class Migration(migrations.Migration):

    dependencies = [
        ('inscricoes', '0004_politicaprivacidade_imagem_pagto_and_more'),
    ]

    operations = [
        # --- MINISTÉRIO.ativo: aplica no DB só se não existir
        migrations.RunSQL(SQL_ADD_ATIVO, reverse_sql=migrations.RunSQL.noop),

        # E garante o State do Django (sem tocar o DB de novo)
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AddField(
                    model_name='ministerio',
                    name='ativo',
                    field=models.BooleanField(default=True),
                ),
            ],
        ),

        # --- ALOCACAO_GRUPO.evento_id (idempotente)
        migrations.RunSQL(SQL_ADD_EVENTO_COL, reverse_sql=migrations.RunSQL.noop),

        # State: adiciona o FK no Django inicialmente como null=True
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AddField(
                    model_name='alocacaogrupo',
                    name='evento',
                    field=models.ForeignKey(
                        related_name='alocacoes_grupo',
                        to='inscricoes.eventoacampamento',
                        on_delete=django.db.models.deletion.CASCADE,
                        null=True,  # temporário até popular e travar NOT NULL
                    ),
                ),
            ],
        ),

        # Popular evento_id a partir de inscricao
        migrations.RunPython(copy_evento_from_inscricao, migrations.RunPython.noop),

        # Tentar travar NOT NULL apenas se já não houver nulos
        migrations.RunSQL(SQL_SET_NOT_NULL, reverse_sql=migrations.RunSQL.noop),

        # Atualiza o State para null=False depois de popular
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AlterField(
                    model_name='alocacaogrupo',
                    name='evento',
                    field=models.ForeignKey(
                        related_name='alocacoes_grupo',
                        to='inscricoes.eventoacampamento',
                        on_delete=django.db.models.deletion.CASCADE,
                        null=False,
                    ),
                ),
            ],
        ),

        # FK e índice idempotentes
        migrations.RunSQL(SQL_ADD_FK, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(SQL_ADD_INDEX, reverse_sql=migrations.RunSQL.noop),
    ]
