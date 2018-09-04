import json
import dataclasses
import base64
import os

import click
import clipboard
from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class JSONDataclassEncoder(json.JSONEncoder):

    def default(self, object_):
        if dataclasses.is_dataclass(object_):
            return dataclasses.asdict(object_)
        return super().default(object_)


class DataclassDatabase:

    def __init__(self, database_path, class_):
        self.class_ = class_
        self.database_path = database_path + '.json'
        self.database = None
        self.n_entries = None
        try:
            self.load()
        except FileNotFoundError:
            self.init()

    def get(self, name):
        if name not in self.database['data']:
            raise DoesNotExistError
        return self.database['data'][name]

    def new(self, name, instance):
        if name in self.database['data']:
            raise AlreadyExistsError
        self.database['data'][name] = instance
        self.update_n_entries()
        self.save()

    def remove(self, name):
        if name not in self.database['data']:
            raise DoesNotExistError
        del self.database['data'][name]
        self.update_n_entries()
        self.save()

    def save(self):
        with open(self.database_path, 'w') as f:
            json.dump(self.database, f, cls=JSONDataclassEncoder, indent=4, sort_keys=True)

    def load(self):
        with open(self.database_path, 'r') as f:
            database_as_dict = json.load(f)
            if database_as_dict['class'] != self.class_.__name__:
                raise DatabaseClassMismatchError
            # Convert the dicts back to dataclass objects
            self.database = {'class': database_as_dict['class'], 'data': {}}
            for key, object_as_dict in database_as_dict['data'].items():
                self.database['data'][key] = self.class_(*object_as_dict.values())
            self.update_n_entries()

    def init(self):
        self.database = {'class': self.class_.__name__, 'data': {}}
        self.update_n_entries()
        self.save()

    def drop(self):
        self.database['data'] = {}
        self.update_n_entries()
        self.save()

    def update_n_entries(self):
        self.n_entries = len(self.database['data'])

    def __iter__(self):
        for name, object_ in self.database['data'].items():
            yield name, object_

    def __contains__(self, name):
        if name in self.database['data']:
            return True
        return False


class DoesNotExistError(Exception):
    pass


class AlreadyExistsError(Exception):
    pass


class DatabaseClassMismatchError(Exception):
    pass


@dataclasses.dataclass()
class Site:
    login: str
    password: str


@dataclasses.dataclass()
class User:
    username: str
    encrypted_data_key: str
    salt: str


def abort_if_false(context, _, value):
    if not value:
        context.abort()


@click.group()
def cli():
    pass


@cli.group()
@click.pass_context
def sites(context):
    """Manage your sites."""
    site_database = DataclassDatabase('sites', Site)
    context.obj = {'site_database': site_database}


@sites.command()
@click.option('--name', type=str, help='Name of the new site.', prompt=True)
@click.option('--login', type=str, help='Login information of the new site.', prompt=True)
@click.option('--password', type=str, help='Password of the new site.', prompt=True, hide_input=True)
@click.pass_context
def new(context, name, login, password):
    """Add a new site to the database."""
    site_database = context.obj['site_database']
    site = Site(login, password)
    try:
        site_database.new(name, site)
    except AlreadyExistsError:
        click.echo(f'Error: A site with the name "{name}" already exists. Please choose another name.')
    else:
        click.echo(f'Added site with name "{name}".')


@sites.command()
@click.option('--name', type=str, help='Name of the site.', prompt=True)
@click.option('--yes', is_flag=True, callback=abort_if_false, expose_value=False,
              prompt=f'Are you sure you want to remove the site?')
@click.pass_context
def remove(context, name):
    """Remove a site from the database."""
    site_database = context.obj['site_database']
    try:
        site_database.remove(name)
    except DoesNotExistError:
        click.echo(f'Error: A site with the name "{name}" does not exist.')
    else:
        click.echo(f'Removed the site with the name "{name}".')


@sites.command()
@click.option('--name', type=str, help='Name of the site.', prompt=True)
@click.option('--login', 'copy_login', help='Copy the login instead of the password.', is_flag=True)
@click.pass_context
def get(context, name, copy_login):
    """Copy the password of a site to the clipboard."""
    site_database = context.obj['site_database']
    try:
        site = site_database.get(name)
    except DoesNotExistError:
        click.echo(f'Error: A site with the name "{name}" does not exist.')
    else:
        if copy_login:
            clipboard.copy(site.login)
            click.echo('Copied login to clipboard.')
        else:
            clipboard.copy(site.password)
            click.echo('Copied password to clipboard.')


@sites.command()
@click.option('--yes', is_flag=True, callback=abort_if_false, expose_value=False,
              prompt=f'Are you sure you want to drop all sites from the database?')
@click.pass_context
def drop(context):
    """Drop all entries from the site database."""
    site_database = context.obj['site_database']
    site_database.drop()
    click.echo('Database dropped.')


@sites.command()
@click.pass_context
def ls(context):
    """List all sites in the database."""
    site_database = context.obj['site_database']
    if site_database.n_entries == 0:
        click.echo('0 sites in database.')
    else:
        if site_database.n_entries == 1:
            click.echo(f'{site_database.n_entries} site in database:')
        else:
            click.echo(f'{site_database.n_entries} sites in database:')
        for name, site in site_database:
            click.echo(f'Name: {name}, Login: {site.login}, Password: {site.password}')


@cli.group()
@click.pass_context
def account(context):
    """Manage your account."""
    user_database = DataclassDatabase('users', User)
    context.obj = {'user_database': user_database}


def validate_username(context, _param, username):
    user_database = context.obj['user_database']
    if username in user_database:
        raise click.BadParameter(
            f'A user with the username "{username}" already exists. Please choose another username.')
    return username


def validate_password(_context, _param, password):
    confirm_password = click.prompt('Confirm password', type=str, hide_input=True)
    if password != confirm_password:
        raise click.BadParameter('Passwords not identical.')
    return password


@account.command()
@click.option('--username', type=str, help='Username for the new account.', prompt=True, callback=validate_username)
@click.option('--password', type=str, help='Password for the new account.', prompt=True, hide_input=True,
              callback=validate_password)
@click.pass_context
def new(context, username, password):
    """Create a new account."""
    salt = os.urandom(16)
    key_derivation_function = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
        backend=default_backend()
    )
    user_key = base64.urlsafe_b64encode(key_derivation_function.derive(password.encode()))
    data_key = Fernet.generate_key()
    fernet = Fernet(user_key)
    encrypted_data_key = fernet.encrypt(data_key)
    user_database = context.obj['user_database']
    user = User(username, encrypted_data_key.decode(), base64.b64encode(salt).decode())
    user_database.new(username, user)
    click.echo(f'Created a new account with the username "{username}".')


@account.command()
def sign_in():
    """Sign in to your account."""
    pass


@account.command()
def sign_out():
    """Sign out of your account."""
    pass


def main():
    pass


if __name__ == '__main__':
    main()
