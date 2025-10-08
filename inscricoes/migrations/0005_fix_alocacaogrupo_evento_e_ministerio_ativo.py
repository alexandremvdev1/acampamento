from django.db import migrations, models
import django.db.models.deletion

def copy_evento_from_inscricao(apps, schema_editor):
    with schema_editor.connection.cursor() as cur:
        cur.execute("""
            UPDATE inscricoes_alocacaogrupo ag
            SET evento_id = i.evento_id
            FROM inscricoes_inscricao i
            WHERE ag.inscricao_id = i.id AND ag.evento_id IS NULL
        """)

class Migration(migrations.Migration):

    dependencies = [
        ('inscricoes', '0004_politicaprivacidade_imagem_pagto_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='ministerio',
            name='ativo',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='alocacaogrupo',
            name='evento',
            field=models.ForeignKey(
                related_name='alocacoes_grupo',
                to='inscricoes.eventoacampamento',
                on_delete=django.db.models.deletion.CASCADE,
                null=True,   # temporário para popular
            ),
        ),
        migrations.RunPython(copy_evento_from_inscricao, migrations.RunPython.noop),
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
        migrations.AddIndex(
            model_name='alocacaogrupo',
            index=models.Index(fields=['evento'], name='alocgrupo_evento_idx'),
        ),
    ]
