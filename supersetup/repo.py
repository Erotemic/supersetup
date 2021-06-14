
import re
from os.path import exists
from os.path import join
from os.path import dirname
from os.path import abspath

import ubelt as ub
import git as gitpython


class ShellException(Exception):
    """
    Raised when shell returns a non-zero error code
    """


class DirtyRepoError(Exception):
    """
    If the repo is in an unexpected state, its very easy to break things using
    automated scripts. To be safe, we don't do anything. We ensure this by
    raising this error.
    """


def parse_version(package):
    """
    Statically parse the version number from __init__.py

    CommandLine:
        python -c "import setup; print(setup.parse_version('netharn'))"
    """
    import ast
    init_fpath = join(dirname(__file__), package, '__init__.py')
    with open(init_fpath) as file_:
        sourcecode = file_.read()
    pt = ast.parse(sourcecode)
    class VersionVisitor(ast.NodeVisitor):
        def visit_Assign(self, node):
            for target in node.targets:
                if target.id == '__version__':
                    self.version = node.value.s
    visitor = VersionVisitor()
    visitor.visit(pt)
    return visitor.version


class GitURL(ub.NiceRepr):
    """
    Represent and transform git urls between protocols defined in [3]_.

    The code in GitURL is largely derived from [1]_ and [2]_.
    Credit to @coala and @FriendCode.

    Note:
        while this code aims to suport protocols defined in [3]_, it is only
        tested for specific use cases and therefore might need to be improved.

    References:
        .. [1] https://github.com/coala/git-url-parse
        .. [2] https://github.com/FriendCode/giturlparse.py
        .. [3] https://git-scm.com/docs/git-clone#URLS

    Example:
        >>> # xdoctest: +SKIP
        >>> self = GitURL('git@gitlab.kitware.com:computer-vision/netharn.git')
        >>> print(ub.repr2(self.parts()))
        >>> print(self.format('ssh'))
        >>> print(self.format('https'))
        >>> self = GitURL('https://gitlab.kitware.com/computer-vision/netharn.git')
        >>> print(ub.repr2(self.parts()))
        >>> print(self.format('ssh'))
        >>> print(self.format('https'))
    """
    SYNTAX_PATTERNS = {
        # git allows for a url style syntax
        'url': re.compile(r'(?P<transport>\w+://)'
                          r'((?P<user>\w+[^@]*@))?'
                          r'(?P<host>[a-z0-9_.-]+)'
                          r'((?P<port>:[0-9]+))?'
                          r'/(?P<path>.*\.git)'),
        # git allows for ssh style syntax
        'ssh': re.compile(r'(?P<user>\w+[^@]*@)'
                          r'(?P<host>[a-z0-9_.-]+)'
                          r':(?P<path>.*\.git)'),
    }

    r"""
    Ignore:
        # Helper to build the parse pattern regexes
        def named(key, regex):
            return '(?P<{}>{})'.format(key, regex)

        def optional(pat):
            return '({})?'.format(pat)

        parse_patterns = {}
        # Standard url format
        transport = named('transport', r'\w+://')
        user = named('user', r'\w+[^@]*@')
        host = named('host', r'[a-z0-9_.-]+')
        port = named('port', r':[0-9]+')
        path = named('path', r'.*\.git')

        pat = ''.join([transport, optional(user), host, optional(port), '/', path])
        parse_patterns['url'] = pat

        pat = ''.join([user, host, ':', path])
        parse_patterns['ssh'] = pat
        print(ub.repr2(parse_patterns))
    """

    def __init__(self, url):
        self._url = url
        self._parts = None

    def __nice__(self):
        return self._url

    def parts(self):
        """
        Parses a GIT URL and returns an info dict.

        Returns:
            dict: info about the url

        Raises:
            Exception : if parsing fails
        """
        info = {
            'syntax': '',
            'host': '',
            'user': '',
            'port': '',
            'path': None,
            'transport': '',
        }

        for syntax, regex in self.SYNTAX_PATTERNS.items():
            match = regex.search(self._url)
            if match:
                info['syntax'] = syntax
                info.update(match.groupdict())
                break
        else:
            raise Exception('Invalid URL {!r}'.format(self._url))

        # change none to empty string
        for k, v in info.items():
            if v is None:
                info[k] = ''
        return info

    def format(self, protocol):
        """
        Change the protocol of the git URL
        """
        parts = self.parts()
        if protocol == 'ssh':
            parts['user'] = 'git@'
            url = ''.join([
                parts['user'], parts['host'], ':', parts['path']
            ])
        else:
            parts['transport'] = protocol + '://'
            parts['port'] = ''
            parts['user'] = ''
            url = ''.join([
                parts['transport'], parts['user'], parts['host'],
                parts['port'], '/', parts['path']
            ])
        return url


class Repo(ub.NiceRepr):
    """
    Abstraction that references a git repository, and is able to manipulate it.

    A common use case is to define a `remote` and a `code_dpath`, which lets
    you check and ensure that the repo is cloned and on a particular branch.
    You can also query its status, and pull, and perform custom git commands.

    Args:
        *args: name, dpath, code_dpath, remotes, remote, branch

    Attributes:
        All names listed in args are attributse. In addition, the class also
        exposes these derived attributes.

        url (URI): where the primary location is

    Example:
        >>> # xdoctest: +SKIP
        >>> # Here is a simple example referencing ubelt
        >>> from supersetup.repo import *  # NOQA

        Repo(dpath='.')


        >>> import ubelt as ub
        >>> repo = Repo(
        >>>     remote='https://github.com/Erotemic/ubelt.git',
        >>>     code_dpath=ub.ensuredir(ub.expandpath('~/tmp/demo-repos')),
        >>> )
        >>> print('repo = {}'.format(repo))
        >>> repo.check()
        >>> repo.ensure()
        >>> repo.check()
        >>> repo.status()
        >>> repo._cmd('python setup.py build')
        >>> repo._cmd('./run_doctests.sh')
        repo = <Repo('ubelt')>

        >>> # Here is a less simple example referencing ubelt
        >>> from super_setup import *
        >>> import ubelt as ub
        >>> repo = Repo(
        >>>     name='ubelt-local',
        >>>     remote='github',
        >>>     branch='master',
        >>>     remotes={
        >>>         'github': 'https://github.com/Erotemic/ubelt.git',
        >>>         'fakemirror': 'https://gitlab.com/Erotemic/ubelt.git',
        >>>     },
        >>>     code_dpath=ub.ensuredir(ub.expandpath('~/tmp/demo-repos')),
        >>> )
        >>> print('repo = {}'.format(repo))
        >>> repo.ensure()
        >>> repo._cmd('python setup.py build')
        >>> repo._cmd('./run_doctests.sh')
    """
    def __init__(repo, **kwargs):
        repo.name = kwargs.pop('name', None)
        repo.dpath = kwargs.pop('dpath', None)
        repo.code_dpath = kwargs.pop('code_dpath', None)
        repo.remotes = kwargs.pop('remotes', None)
        repo.remote = kwargs.pop('remote', None)
        repo.branch = kwargs.pop('branch', 'master')

        repo._logged_lines = []
        repo._logged_cmds = []

        if repo.remote is None:

            if repo.remotes is None:
                if repo.dpath is not None:
                    gitrepo = gitpython.Repo(repo.dpath)
                    repo.remotes = gitrepo.remotes

            if repo.remotes is None:
                raise ValueError('must specify some remote')
            else:
                if len(repo.remotes) > 1:
                    raise ValueError('remotes are ambiguous, specify one')
                elif len(repo.remotes) == 0:
                    raise ValueError('must specify some remote')
                else:
                    repo.remote = ub.peek(repo.remotes)
        else:
            if repo.remotes is None:
                _default_remote = 'origin'
                repo.remotes = {
                    _default_remote: repo.remote
                }
                repo.remote = _default_remote

        repo.url = repo.remotes[repo.remote]

        if repo.name is None:
            suffix = repo.url.split('/')[-1]
            repo.name = suffix.split('.git')[0]

        if repo.dpath is None:
            repo.dpath = join(repo.code_dpath, repo.name)

        repo.pkg_dpath = join(repo.dpath, repo.name)

        for path_attr in ['dpath', 'code_dpath']:
            path = getattr(repo, path_attr)
            if path is not None:
                setattr(repo, path_attr, ub.expandpath(path))

        repo.verbose = kwargs.pop('verbose', 3)
        if kwargs:
            raise ValueError('unknown kwargs = {}'.format(kwargs.keys()))

        repo._pygit = None

    def set_protocol(self, protocol):
        """
        Changes the url protocol to either ssh or https

        Args:
            protocol (str): can be ssh or https
        """
        # Update base url to use the requested protocol
        gurl = GitURL(self.url)
        self.url = gurl.format(protocol)
        # Update all remote urls to use the requested protocol
        for key in list(self.remotes.keys()):
            self.remotes[key] = GitURL(self.remotes[key]).format(protocol)

    def info(repo, msg):
        repo._logged_lines.append(('INFO', 'INFO: ' + msg))
        if repo.verbose >= 1:
            print(msg)

    def debug(repo, msg):
        repo._logged_lines.append(('DEBUG', 'DEBUG: ' + msg))
        if repo.verbose >= 1:
            print(msg)

    def _getlogs(repo):
        return '\n'.join([t[1] for t in repo._logged_lines])

    def __nice__(repo):
        return '{}, branch={}'.format(repo.name, repo.branch)

    def _cmd(repo, command, cwd=ub.NoParam, verbose=ub.NoParam):
        if verbose is ub.NoParam:
            verbose = repo.verbose
        if cwd is ub.NoParam:
            cwd = repo.dpath

        repo._logged_cmds.append((command, cwd))
        repo.debug('Run {!r} in {!r}'.format(command, cwd))

        info = ub.cmd(command, cwd=cwd, verbose=verbose)

        if verbose:
            if info['out'].strip():
                repo.info(info['out'])

            if info['err'].strip():
                repo.debug(info['err'])

        if info['ret'] != 0:
            raise ShellException(ub.repr2(info))
        return info

    @property
    # @ub.memoize_property
    def pygit(repo):
        """ pip install gitpython """
        if repo._pygit is None:
            repo._pygit = gitpython.Repo(repo.dpath)
        return repo._pygit

    def develop(repo):
        """
        Install each repo in development mode.
        """
        # NOTE: We need ensure build requirements are satisfied!
        build_req_fpath = join(repo.dpath, 'requirements/build.txt')
        if exists(build_req_fpath):
            repo._cmd('pip install -r {}'.format(build_req_fpath), cwd=repo.dpath)

        if ub.WIN32:
            # We can't run a shell file on win32, so lets hope this works
            import warnings
            warnings.warn('super_setup develop may not work on win32')
            repo._cmd('pip install -e .', cwd=repo.dpath)
        else:
            repo._cmd('pip install -e .', cwd=repo.dpath)
            # devsetup_script_fpath = join(repo.dpath, 'run_developer_setup.sh')
            # if not exists(devsetup_script_fpath):
            #     raise AssertionError('Assume we always have run_developer_setup.sh: repo={!r}'.format(repo))
            # repo._cmd(devsetup_script_fpath, cwd=repo.dpath)

    @classmethod
    def demo(Repo, ensure=True):
        repo = Repo(
            remote='https://github.com/Erotemic/ubelt.git',
            code_dpath=ub.ensuredir(ub.expandpath('~/tmp/demo-repos')),
        )
        if ensure:
            repo.ensure()
        return repo

    def doctest(repo):
        if ub.WIN32:
            raise NotImplementedError('doctest does not yet work on windows')

        devsetup_script_fpath = join(repo.dpath, 'run_doctests.sh')
        if not exists(devsetup_script_fpath):
            raise AssertionError('Assume we always have run_doctests.sh: repo={!r}'.format(repo))
        repo._cmd(devsetup_script_fpath, cwd=repo.dpath)

    def clone(repo):
        if exists(repo.dpath):
            raise ValueError('cannot clone into non-empty directory')
        args = '--recursive'
        # NOTE: if the remote branch does not exist this will fail
        if repo.branch is not None:
            args += ' -b {}'.format(repo.branch)
        try:
            command = 'git clone {args} {url} {dpath}'.format(
                args=args, url=repo.url, dpath=repo.dpath)
            repo._cmd(command, cwd=repo.code_dpath)
        except Exception as ex:
            text = repr(ex)
            if 'Remote branch' in text and 'not found' in text:
                print('ERROR: It looks like the remote branch you asked for doesnt exist')
                print('ERROR: Caused by: ex = {}'.format(text))
                raise Exception('Cannot find branch {} for repo {}'.format(repo.branch, repo))
            raise

    def _assert_clean(repo):
        if repo.pygit.is_dirty():
            raise DirtyRepoError('The repo={} is dirty'.format(repo))

    def check(repo):
        repo.ensure(dry=True)

    def versions(repo):
        """
        Print current version information
        """
        fmtkw = {}
        fmtkw['pkg'] = parse_version(repo.pkg_dpath) + ','
        fmtkw['sha1'] = repo._cmd('git rev-parse HEAD', verbose=0)['out'].strip()
        try:
            fmtkw['tag'] = repo._cmd('git describe --tags', verbose=0)['out'].strip() + ','
        except ShellException:
            fmtkw['tag'] = '<None>,'
        fmtkw['branch'] = repo.pygit.active_branch.name + ','
        fmtkw['repo'] = repo.name + ','
        repo.info('repo={repo:<14} pkg={pkg:<12} tag={tag:<18} branch={branch:<10} sha1={sha1}'.format(
            **fmtkw))

    def ensure_clone(repo):
        if exists(repo.dpath):
            repo.debug('No need to clone existing repo={}'.format(repo))
        else:
            repo.debug('Clone non-existing repo={}'.format(repo))
            repo.clone()

    def upgrade(repo, dry=False):
        """
        Look for a "dev" branch with a higher version number and switch to that.

        Example:
            >>> from super_setup import *
            >>> import ubelt as ub
            >>> repo = Repo.demo()
            >>> print('repo = {}'.format(repo))
            >>> repo.upgrade()
        """
        remote = repo._registered_remote()
        repo._cmd('git fetch {}'.format(remote.name))
        repo.info('Fetch was successful')
        remote_branchnames = [ref.remote_head for ref in remote.refs]
        print('remote_branchnames = {!r}'.format(remote_branchnames))

        # Find all the dev branches
        dev_branches_ = [ref for ref in remote.refs
                         if ref.remote_head.startswith('dev/')]

        dev_branches = []
        version_tuples = []
        for ref in dev_branches_:
            try:
                tup = tuple(map(int, ref.remote_head.split('dev/')[1].split('.')))
                dev_branches.append(ref)
                version_tuples.append(tup)
            except Exception:
                pass

        latest_ref = dev_branches[ub.argmax(version_tuples)]
        latest_branch = latest_ref.remote_head

        if repo.pygit.active_branch.name == latest_branch:
            repo.info('Already on the latest dev branch')
        else:
            try:
                repo._cmd('git checkout {}'.format(latest_branch))
            except ShellException:
                repo.debug('Checkout failed. Branch name might be ambiguous. Trying again')
                try:
                    repo._cmd('git checkout -b {} {}/{}'.format(latest_branch, remote, latest_branch))
                except ShellException:
                    raise Exception('does the branch exist on the remote?')

    def _registered_remote(repo, dry=False):
        # Ensure we have the right remote
        try:
            remote = repo.pygit.remotes[repo.remote]
        except IndexError:
            repo._ensure_remotes(dry=dry)
            try:
                remote = repo.pygit.remotes[repo.remote]
            except IndexError:
                repo.debug('Something went wrong, cannot find remote in git')
                remote = None

        if remote is not None:
            try:
                if not remote.exists():
                    raise IndexError
                else:
                    repo.debug('The requested remote={} name exists'.format(remote))
            except IndexError:
                repo.debug('WARNING: remote={} does not exist'.format(remote))
            else:
                if not remote.exists():
                    repo.debug('Requested remote does NOT exist')
        return remote

    def _ensure_remotes(repo, dry=True):
        """
        Ensures the the registred remotes exists in the git repo.
        """
        for remote_name, remote_url in repo.remotes.items():
            try:
                remote = repo.pygit.remotes[remote_name]
                have_urls = list(remote.urls)
                if remote_url not in have_urls:
                    # TODO supress this warning if its just a git vs https
                    # thing using GitURL
                    print('WARNING: REMOTE NAME EXISTS BUT URL IS NOT {}. '
                          'INSTEAD GOT: {}'.format(remote_url, have_urls))
            except (IndexError):
                try:
                    print('NEED TO ADD REMOTE {}->{} FOR {}'.format(
                        remote_name, remote_url, repo))
                    if not dry:
                        repo._cmd('git remote add {} {}'.format(remote_name, remote_url))
                    else:
                        raise AssertionError('In dry mode, cannot ensure remotes')
                except ShellException:
                    if remote_name == repo.remote:
                        # Only error if the main remote is not available
                        raise

    def ensure(repo, dry=False):
        """
        Ensure that the repo is checked out on your local machine, that the
        correct branch is checked out, and the upstreams are targeting the
        correct remotes.
        """
        if repo.verbose > 0:
            if dry:
                repo.debug(ub.color_text('Checking {}'.format(repo), 'blue'))
            else:
                repo.debug(ub.color_text('Ensuring {}'.format(repo), 'blue'))

        if not exists(repo.dpath):
            repo.debug('NEED TO CLONE {}: {}'.format(repo, repo.url))
            if dry:
                return

        repo.ensure_clone()

        repo._assert_clean()

        # Ensure we have the right remote
        remote = repo._registered_remote(dry=dry)

        if remote is not None:
            try:
                if not remote.exists():
                    raise IndexError
                else:
                    repo.debug('The requested remote={} name exists'.format(remote))
            except IndexError:
                repo.debug('WARNING: remote={} does not exist'.format(remote))
            else:
                if remote.exists():
                    repo.debug('Requested remote does exists')
                    remote_branchnames = [ref.remote_head for ref in remote.refs]
                    if repo.branch not in remote_branchnames:
                        repo.info('Branch name not found in local remote. Attempting to fetch')
                        if dry:
                            repo.info('dry run, not fetching')
                        else:
                            repo._cmd('git fetch {}'.format(remote.name))
                            repo.info('Fetch was successful')
                else:
                    repo.debug('Requested remote does NOT exist')

            # Ensure the remote points to the right place
            if repo.url not in list(remote.urls):
                repo.debug(ub.paragraph(
                    '''
                    'WARNING: The requested url={} disagrees with remote
                    urls={}
                    ''').format(repo.url, list(remote.urls)))

                if dry:
                    repo.info('Dry run, not updating remote url')
                else:
                    repo.info('Updating remote url')
                    repo._cmd('git remote set-url {} {}'.format(repo.remote, repo.url))

            # Ensure we are on the right branch
            try:
                active_branch_name = repo.pygit.active_branch.name
            except TypeError:
                # We may be on a tag, not a branch
                candidates = [tag for tag in repo.pygit.tags if tag.name == repo.branch]
                if len(candidates) != 1:
                    raise
                else:
                    # branch is actually a tag
                    assert len(candidates) == 1
                    want_tag = candidates[0]
                    is_on_correct_commit = (
                        repo.pygit.head.commit.hexsha == want_tag.commit.hexsha
                    )
                    ref_is_tag = True
            else:
                ref_is_tag = False
                tracking_branch = repo.pygit.active_branch.tracking_branch()
                is_on_correct_commit = repo.branch == active_branch_name

            if not is_on_correct_commit:
                repo.debug('NEED TO SET BRANCH TO {} for {}'.format(repo.branch, repo))
                if dry:
                    repo.info('Dry run, not setting branch')
                else:
                    try:
                        repo._cmd('git checkout {}'.format(repo.branch))
                    except ShellException:
                        repo.debug('Checkout failed. Branch name might be ambiguous. Trying again')
                        try:
                            repo._cmd('git fetch {}'.format(remote.name))
                            repo._cmd('git checkout -b {} {}/{}'.format(repo.branch, repo.remote, repo.branch))
                        except ShellException:
                            raise Exception('does the branch exist on the remote?')

            if not ref_is_tag:
                if tracking_branch is None or tracking_branch.remote_name != repo.remote:
                    repo.debug('NEED TO SET UPSTREAM FOR FOR {}'.format(repo))

                    try:
                        remote = repo.pygit.remotes[repo.remote]
                        if not remote.exists():
                            raise IndexError
                    except IndexError:
                        repo.debug('WARNING: remote={} does not exist'.format(remote))
                    else:
                        if remote.exists():
                            remote_branchnames = [ref.remote_head for ref in remote.refs]
                            if repo.branch not in remote_branchnames:
                                if dry:
                                    repo.info('Branch name not found in local remote. Dry run, use ensure to attempt to fetch')
                                else:
                                    repo.info('Branch name not found in local remote. Attempting to fetch')
                                    repo._cmd('git fetch {}'.format(repo.remote))

                                    remote_branchnames = [ref.remote_head for ref in remote.refs]
                                    if repo.branch not in remote_branchnames:
                                        raise Exception('Branch name still does not exist')

                            if not dry:
                                repo._cmd('git branch --set-upstream-to={remote}/{branch} {branch}'.format(
                                    remote=repo.remote, branch=repo.branch
                                ))
                            else:
                                repo.info('Would attempt to set upstream')

        # Check if the current head is tagged
        head_tags = [
            tag for tag in repo.pygit.tags
            if tag.commit.hexsha == repo.pygit.head.commit.hexsha
        ]

        # Print some status
        try:
            repo.debug(' * branch = {} -> {}'.format(
                repo.pygit.active_branch.name,
                repo.pygit.active_branch.tracking_branch(),
            ))
        except Exception:
            pass

        if head_tags:
            repo.debug(' * head_tags = {}'.format(head_tags))

    def pull(repo):
        repo._assert_clean()
        # TODO: In past runs I've gotten the error:
        # Your configuration specifies to merge with the ref
        # 'refs/heads/dev/0.0.2' from the remote, but no such ref was fetched.
        # Doing an ensure seemed to fix it. We should do something to handle
        # this case ellegantly.
        repo._cmd('git pull')

    def status(repo):
        repo._cmd('git status')
