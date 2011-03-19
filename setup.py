from setuptools import setup, find_packages

setup(name='favicon',
      version='0.1',
      description='favicon service',
      packages=find_packages(),
      install_requires = ['BeautifulSoup>=3.2.0',
                          'CherryPy>=3.1.2',
                          'Jinja2>=2.5.5',
                          'python-memcached>=1.47'],
      author = 'Sandesh Devaraju',
      author_email = 'scouredimage@gmail.com',
)
