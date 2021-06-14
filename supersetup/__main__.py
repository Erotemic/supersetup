#!/usr/bin/env python
# PYTHON_ARGCOMPLETE_OK
# -*- coding: utf-8 -*-

import click
import functools
import ubelt as ub
from os.path import exists
from supersetup.repo import Repo, DirtyRepoError, GitURL


def worker(repo, funcname, kwargs):
    repo.verbose = 0
    func = getattr(repo, funcname)
    func(**kwargs)
    return repo


class RepoRegistry(ub.NiceRepr):
    def __init__(registery, repos):
        registery.repos = repos

    def __nice__(registery):
        return ub.repr2(registery.repos, si=1, nl=1)

    def apply(registery, funcname, num_workers=0, **kwargs):
        print(ub.color_text('--- APPLY {} ---'.format(funcname), 'white'))
        print(' * num_workers = {!r}'.format(num_workers))

        if num_workers == 0:
            processed_repos = []
            for repo in registery.repos:
                print(ub.color_text('--- REPO = {} ---'.format(repo), 'blue'))
                try:
                    getattr(repo, funcname)(**kwargs)
                except DirtyRepoError:
                    print(ub.color_text('Ignoring dirty repo={}'.format(repo), 'red'))
                processed_repos.append(repo)
        else:
            from concurrent import futures
            # with futures.ThreadPoolExecutor(max_workers=num_workers) as pool:
            with futures.ProcessPoolExecutor(max_workers=num_workers) as pool:
                tasks = []
                for i, repo in enumerate(registery.repos):
                    future = pool.submit(worker, repo, funcname, kwargs)
                    future.repo = repo
                    tasks.append(future)

                processed_repos = []
                for future in futures.as_completed(tasks):
                    repo = future.repo
                    print(ub.color_text('--- REPO = {} ---'.format(repo), 'blue'))
                    try:
                        repo = future.result()
                    except DirtyRepoError:
                        print(ub.color_text('Ignoring dirty repo={}'.format(repo), 'red'))
                    else:
                        print(repo._getlogs())
                    processed_repos.append(repo)

        print(ub.color_text('--- FINISHED APPLY {} ---'.format(funcname), 'white'))

        SHOW_CMDLOG = 1

        if SHOW_CMDLOG:

            print('LOGGED COMMANDS')
            import os
            ORIG_CWD = MY_CWD = os.getcwd()
            for repo in processed_repos:
                print('# --- For repo = {!r} --- '.format(repo))
                for t in repo._logged_cmds:
                    cmd, cwd = t
                    if cwd is None:
                        cwd = os.get_cwd()
                    if cwd != MY_CWD:
                        print('cd ' + ub.shrinkuser(cwd))
                        MY_CWD = cwd
                    print(cmd)
            print('cd ' + ub.shrinkuser(ORIG_CWD))


def determine_code_dpath():
    """
    Returns a good place to put the code for the internal dependencies.

    Returns:
        PathLike: the directory where you want to store your code

    In order, the methods used for determing this are:
        * the `--codedpath` command line flag (may be undocumented in the CLI)
        * the `--codedir` command line flag (may be undocumented in the CLI)
        * the CODE_DPATH environment variable
        * the CODE_DIR environment variable
        * the directory above this script (e.g. if this is in ~/code/repo/super_setup.py then code dir resolves to ~/code)
        * the user's ~/code directory.
    """
    import os
    candidates = [
        ub.argval('--codedir', default=''),
        ub.argval('--codedpath', default=''),
        os.environ.get('CODE_DPATH', ''),
        os.environ.get('CODE_DIR', ''),
    ]
    valid = [c for c in candidates if c != '']
    if len(valid) > 0:
        code_dpath = valid[0]
    else:
        try:
            # This file should be in the top level of a repo, the directory from
            # this file should be the code directory.
            this_fpath = abspath(__file__)
            code_dpath = abspath(dirname(dirname(this_fpath)))
        except NameError:
            code_dpath = ub.expandpath('~/code')

    if not exists(code_dpath):
        code_dpath = ub.expandpath(code_dpath)

    # if CODE_DIR and not exists(CODE_DIR):
    #     import warnings
    #     warnings.warn('environment variable CODE_DIR={!r} was defined, but does not exist'.format(CODE_DIR))

    if not exists(code_dpath):
        raise Exception(ub.codeblock(
            '''
            Please specify a correct code_dir using the CLI or ENV.
            code_dpath={!r} does not exist.
            '''.format(code_dpath)))
    return code_dpath


def make_registry(devel_repos):
    code_dpath = determine_code_dpath()
    CommonRepo = functools.partial(Repo, code_dpath=code_dpath)
    repos = [CommonRepo(**kw) for kw in devel_repos]
    registery = RepoRegistry(repos)
    return registery


def main():
    devel_repos = DEVEL_REPOS
    registery = make_registry(devel_repos)

    only = ub.argval('--only', default=None)
    if only is not None:
        only = only.split(',')
        registery.repos = [repo for repo in registery.repos if repo.name in only]

    num_workers = int(ub.argval('--workers', default=8))
    if ub.argflag('--serial'):
        num_workers = 0

    protocol = ub.argval('--protocol', None)
    if ub.argflag('--https'):
        protocol = 'https'
    if ub.argflag('--http'):
        protocol = 'http'
    if ub.argflag('--ssh'):
        protocol = 'ssh'

    main_repo = None
    MAIN_REPO_NAME = 'netharn'
    for repo in registery.repos:
        if repo.name == MAIN_REPO_NAME:
            main_repo = repo
            break

    HACK_PROTOCOL = True
    if HACK_PROTOCOL:
        if protocol is None:
            # Try to determine if you are using ssh or https and default to that
            for remote in repo.pygit.remotes:
                for url in list(remote.urls):
                    gurl1 = GitURL(url)
                    gurl2 = GitURL(repo.url)
                    if gurl2.parts()['path'] == gurl1.parts()['path']:
                        if gurl1.parts()['syntax'] == 'ssh':
                            protocol = 'ssh'
                        else:
                            protocol = 'https'
                        break
                if protocol is not None:
                    print('Found default protocol = {}'.format(protocol))
                    break

    if protocol is not None:
        for repo in registery.repos:
            repo.set_protocol(protocol)

    default_context_settings = {
        'help_option_names': ['-h', '--help'],
        'allow_extra_args': True,
        'ignore_unknown_options': True}

    @click.group(context_settings=default_context_settings)
    def cli_group():
        pass

    @cli_group.add_command
    @click.command('pull', context_settings=default_context_settings)
    def pull():
        registery.apply('pull', num_workers=num_workers)

    @cli_group.add_command
    @click.command('ensure', context_settings=default_context_settings)
    def ensure():
        """
        Ensure is the live run of "check".
        """
        registery.apply('ensure', num_workers=num_workers)

    @cli_group.add_command
    @click.command('ensure_clone', context_settings=default_context_settings)
    def ensure_clone():
        registery.apply('ensure_clone', num_workers=num_workers)

    @cli_group.add_command
    @click.command('check', context_settings=default_context_settings)
    def check():
        """
        Check is just a dry run of "ensure".
        """
        registery.apply('check', num_workers=num_workers)

    @cli_group.add_command
    @click.command('status', context_settings=default_context_settings)
    def status():
        registery.apply('status', num_workers=num_workers)

    @cli_group.add_command
    @click.command('develop', context_settings=default_context_settings)
    def develop():
        registery.apply('develop', num_workers=0)

    @cli_group.add_command
    @click.command('doctest', context_settings=default_context_settings)
    def doctest():
        registery.apply('doctest')

    @cli_group.add_command
    @click.command('versions', context_settings=default_context_settings)
    def versions():
        registery.apply('versions')

    @cli_group.add_command
    @click.command('upgrade', context_settings=default_context_settings)
    def upgrade():
        assert main_repo is not None
        main_repo.upgrade()

    cli_group()


if __name__ == '__main__':
    main()
