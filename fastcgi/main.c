
#include "fcgi_stdio.h"
#include <stdlib.h>
// #include <list.h>

/*
int allocate_mem(int size)
{
    addr = malloc(size)
    if NULL != addr:
        return;
}
*/

int main()
{
    const char *Data = ""
        "{"
            "\"message\": \"Hello FastCGI web app\""
        "}";
    while(FCGI_Accept() >=0 )
        printf("Content-type: application/json\r\n"
               "\r\n"
               "%s", Data);
    return 0;
}